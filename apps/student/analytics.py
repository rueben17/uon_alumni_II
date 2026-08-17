"""
Scholarship exercise analytics -- one function per metric group, each
returning plain dicts/lists of dicts computed via DB-side aggregation
(no per-applicant Python loop). apps/student/views.py's
ScholarshipAnalyticsExportView renders these into an .xlsx workbook.

Ground truth, verified against apps/student/models.py and
apps/staff/models.py (2026-08-14) -- corrects several assumed names a
prior spec got wrong:
  - "Applicant" is ScholarshipApplication (this app), not a model
    called Applicant.
  - "Evaluation" is InterviewScoreSheet, reached from
    ScholarshipApplication via the OneToOne reverse accessor
    .score_sheet (related_name) -- at most one per applicant.
  - There is no criteria model and no weight field anywhere. The 8
    criterion scores are hardcoded fields directly on
    InterviewScoreSheet, each capped by its own MaxValueValidator.
    SCORE_FIELDS/score_field_max() (apps/student/forms.py) are already
    the single source of truth for those names/caps -- reused here
    rather than re-hardcoded, so the two can't drift apart.
  - InterviewScoreSheet.total_score is a Python @property (sum of the
    8 fields), not a DB column -- _total_score_expr() rebuilds the same
    sum as an F()-expression so it can run inside the database.

Applicants with no evaluation are counted in exercise_totals() but
excluded from every other function below -- each of those filters to
queryset.filter(score_sheet__isnull=False) first (via _evaluated()).

Postgres-only aggregates in use: StdDev (django.db.models -- built in,
but only executes on backends that implement STDDEV_POP/SAMP) and
PercentileCont (defined below -- Django's ORM has no built-in
percentile aggregate; PERCENTILE_CONT is a real Postgres ordered-set
function Django just doesn't wrap). Neither runs on SQLite. Verified
against the real Postgres (Neon) connection, both for correct SQL
execution and, via a literal-VALUES query touching no tables, for
numeric correctness against Python's statistics module (2026-08-14).
"""
from django.db.models import Aggregate, Avg, Case, CharField, Count, F, FloatField, Max, Min, StdDev, Value, When

from apps.student.forms import SCORE_FIELDS, score_field_max
from apps.student.models import County, Gender, ScholarshipApplication

SCORE_BAND_COUNT = 10


class PercentileCont(Aggregate):
    function = "PERCENTILE_CONT"
    name = "percentile_cont"
    output_field = FloatField()
    template = "%(function)s(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"

    def __init__(self, expression, percentile=0.5, **extra):
        super().__init__(expression, percentile=percentile, **extra)


def _total_score_expr(prefix="score_sheet__"):
    """F()-expression summing the 8 criterion scores -- the DB-side
    equivalent of InterviewScoreSheet.total_score."""
    fields = [F(f"{prefix}{name}") for name in SCORE_FIELDS]
    expr = fields[0]
    for field_expr in fields[1:]:
        expr = expr + field_expr
    return expr


TOTAL_POSSIBLE = sum(score_field_max(name) for name in SCORE_FIELDS)


def _base_queryset(queryset):
    return queryset if queryset is not None else ScholarshipApplication.objects.all()


def _evaluated(queryset):
    """Every metric function except exercise_totals() operates only on
    applicants that have a score sheet -- an unevaluated applicant has
    no score to contribute to a mean/median/distribution."""
    return _base_queryset(queryset).filter(score_sheet__isnull=False)


def exercise_totals(queryset=None):
    """Metric group 1. Applicants, evaluated, unevaluated, completion
    rate, distinct evaluators, and the date range of evaluations --
    computed in a single query over the whole (unfiltered-to-evaluated)
    queryset, since unevaluated applicants are meant to be counted
    here."""
    queryset = _base_queryset(queryset)
    stats = queryset.aggregate(
        applicants=Count("id"),
        evaluated=Count("score_sheet"),
        distinct_evaluators=Count("score_sheet__evaluator", distinct=True),
        earliest_evaluation=Min("score_sheet__interview_date"),
        latest_evaluation=Max("score_sheet__interview_date"),
    )
    applicants = stats["applicants"]
    evaluated = stats["evaluated"]
    completion_rate = (evaluated / applicants * 100) if applicants else 0.0
    return {
        "applicants": applicants,
        "evaluated": evaluated,
        "unevaluated": applicants - evaluated,
        "completion_rate": completion_rate,
        "distinct_evaluators": stats["distinct_evaluators"],
        "earliest_evaluation": stats["earliest_evaluation"],
        "latest_evaluation": stats["latest_evaluation"],
    }


def score_distribution(queryset=None):
    """Metric group 2. min/max/mean/median/stdev/Q1/Q3 over the total
    score, plus counts across SCORE_BAND_COUNT equal-width bands
    spanning [0, TOTAL_POSSIBLE]. Two queries: one for the single-row
    statistics, one for the banded counts (Case/When needs an actual
    annotated column to bucket on, not a bare expression)."""
    queryset = _evaluated(queryset)
    total_expr = _total_score_expr()

    stats = queryset.aggregate(
        min=Min(total_expr),
        max=Max(total_expr),
        mean=Avg(total_expr),
        stdev=StdDev(total_expr, sample=False),
        q1=PercentileCont(total_expr, 0.25),
        median=PercentileCont(total_expr, 0.5),
        q3=PercentileCont(total_expr, 0.75),
    )

    band_width = TOTAL_POSSIBLE / SCORE_BAND_COUNT
    whens = []
    band_labels = []
    for i in range(SCORE_BAND_COUNT):
        lower = band_width * i
        upper = band_width * (i + 1)
        label = f"{lower:g}-{upper:g}"
        band_labels.append(label)
        if i == SCORE_BAND_COUNT - 1:
            whens.append(When(total__gte=lower, then=Value(label)))
        else:
            whens.append(When(total__gte=lower, total__lt=upper, then=Value(label)))

    band_counts = dict(
        queryset.annotate(total=total_expr)
        .annotate(band=Case(*whens, output_field=CharField()))
        .values_list("band")
        .annotate(count=Count("id"))
    )
    bands = [{"band": label, "count": band_counts.get(label, 0)} for label in band_labels]

    return {
        "min": stats["min"] or 0,
        "max": stats["max"] or 0,
        "mean": stats["mean"] or 0.0,
        "median": stats["median"] or 0.0,
        "stdev": stats["stdev"] or 0.0,
        "q1": stats["q1"] or 0.0,
        "q3": stats["q3"] or 0.0,
        "bands": bands,
    }


def by_faculty(queryset=None):
    """Metric group 3. One row per faculty present among evaluated
    applicants: count, share of the evaluated total, mean/median/
    highest score. Single query."""
    queryset = _evaluated(queryset)
    total_expr = _total_score_expr()
    rows = list(
        queryset.values("faculty_id", "faculty__faculty_name")
        .annotate(count=Count("id"), mean=Avg(total_expr), median=PercentileCont(total_expr, 0.5), highest=Max(total_expr))
        .order_by("-count")
    )
    total_evaluated = sum(row["count"] for row in rows)
    for row in rows:
        row["faculty_name"] = row.pop("faculty__faculty_name") or "Unspecified"
        row["share_of_total"] = (row["count"] / total_evaluated * 100) if total_evaluated else 0.0
    return rows


def by_county(queryset=None):
    """Metric group 4. One row per county present among evaluated
    applicants: count, mean score, sorted by count descending. Single
    query."""
    queryset = _evaluated(queryset)
    total_expr = _total_score_expr()
    rows = list(
        queryset.values("county_of_residence")
        .annotate(count=Count("id"), mean=Avg(total_expr))
        .order_by("-count")
    )
    labels = {value: str(label) for value, label in County.choices}
    for row in rows:
        row["county_label"] = labels.get(row["county_of_residence"], row["county_of_residence"])
    return rows


def by_gender(queryset=None):
    """Metric group 5. Single query."""
    queryset = _evaluated(queryset)
    total_expr = _total_score_expr()
    rows = list(
        queryset.values("gender")
        .annotate(count=Count("id"), mean=Avg(total_expr), median=PercentileCont(total_expr, 0.5))
        .order_by("-count")
    )
    total_evaluated = sum(row["count"] for row in rows)
    labels = {value: str(label) for value, label in Gender.choices}
    for row in rows:
        row["gender_label"] = labels.get(row["gender"], row["gender"])
        row["share"] = (row["count"] / total_evaluated * 100) if total_evaluated else 0.0
    return rows


def criterion_diagnostics(queryset=None):
    """Metric group 6. Per criterion: mean, max possible, mean as a
    percentage of max, standard deviation, and a low-variance flag
    (stdev below 10% of that criterion's max -- a candidate for removal
    next cycle, since it isn't discriminating between applicants).
    Single query: every criterion's mean/stdev is requested as its own
    aggregate() kwarg in one call, not one query per criterion."""
    queryset = _evaluated(queryset)
    aggregate_kwargs = {}
    for name in SCORE_FIELDS:
        aggregate_kwargs[f"mean_{name}"] = Avg(f"score_sheet__{name}")
        aggregate_kwargs[f"stdev_{name}"] = StdDev(f"score_sheet__{name}", sample=False)
    stats = queryset.aggregate(**aggregate_kwargs)

    rows = []
    for name in SCORE_FIELDS:
        max_possible = score_field_max(name)
        mean = stats[f"mean_{name}"] or 0.0
        stdev = stats[f"stdev_{name}"] or 0.0
        rows.append(
            {
                "criterion": name,
                "label": name.replace("score_", "").replace("_", " ").title(),
                "mean": mean,
                "max_possible": max_possible,
                "mean_pct_of_max": (mean / max_possible * 100) if max_possible else 0.0,
                "stdev": stdev,
                "low_variance_flag": stdev < (0.10 * max_possible) if max_possible else False,
            }
        )
    return rows


def evaluator_consistency(queryset=None):
    """Metric group 7. Per evaluator: applicants evaluated, mean score
    awarded, and the difference from the overall mean (positive =
    lenient, negative = harsh). Two queries: the overall mean, then the
    per-evaluator breakdown."""
    queryset = _evaluated(queryset)
    total_expr = _total_score_expr()
    overall_mean = queryset.aggregate(mean=Avg(total_expr))["mean"] or 0.0

    rows = list(
        queryset.values(
            "score_sheet__evaluator_id",
            "score_sheet__evaluator__user__profile__given_name",
            "score_sheet__evaluator__user__profile__family_name",
        )
        .annotate(count=Count("id"), mean=Avg(total_expr))
        .order_by("-mean")
    )
    for row in rows:
        given = row.pop("score_sheet__evaluator__user__profile__given_name") or ""
        family = row.pop("score_sheet__evaluator__user__profile__family_name") or ""
        row["evaluator_id"] = row.pop("score_sheet__evaluator_id")
        row["evaluator_name"] = f"{given} {family}".strip() or "Unknown"
        row["mean"] = row["mean"] or 0.0
        row["difference_from_overall_mean"] = row["mean"] - overall_mean
    return rows


def cutoff_simulation(queryset=None):
    """Metric group 8. For a cutoff at each decile of TOTAL_POSSIBLE,
    how many evaluated applicants score at or above it, broken down by
    faculty and gender. Two queries regardless of applicant count: one
    to enumerate the small, bounded set of faculties actually present,
    one aggregate() covering every threshold x faculty x gender
    combination via conditional Count(Case(When(...))) -- looping here
    is over that bounded (threshold, faculty, gender) grid to build the
    query, not over applicants."""
    queryset = _evaluated(queryset)
    qs = queryset.annotate(total=_total_score_expr())

    faculties = list(
        qs.values("faculty_id", "faculty__faculty_name").distinct().order_by("faculty__faculty_name")
    )
    genders = [choice[0] for choice in Gender.choices]
    # str(...) the label -- Gender.choices' display labels are
    # gettext_lazy proxies, not plain str. Fine as a dict *value*
    # (str()'d on render), but broken as a dict *key*: json.dumps
    # rejects a __proxy__ key outright (confirmed via the Neon
    # verification run, 2026-08-14), and dict lookups against a literal
    # string key are safer as plain str too rather than relying on
    # __proxy__'s str-compatible __eq__/__hash__.
    gender_labels = {value: str(label) for value, label in Gender.choices}

    thresholds = [TOTAL_POSSIBLE * decile / SCORE_BAND_COUNT for decile in range(1, SCORE_BAND_COUNT + 1)]
    aggregate_kwargs = {}
    for i, threshold in enumerate(thresholds):
        aggregate_kwargs[f"count_{i}"] = Count(Case(When(total__gte=threshold, then=1)))
        for gender in genders:
            aggregate_kwargs[f"count_{i}_gender_{gender}"] = Count(
                Case(When(total__gte=threshold, gender=gender, then=1))
            )
        for faculty in faculties:
            fid = faculty["faculty_id"]
            aggregate_kwargs[f"count_{i}_faculty_{fid}"] = Count(
                Case(When(total__gte=threshold, faculty_id=fid, then=1))
            )
    stats = qs.aggregate(**aggregate_kwargs)

    rows = []
    for i, threshold in enumerate(thresholds):
        rows.append(
            {
                "threshold": threshold,
                "decile": (i + 1) * 10,
                "surviving_count": stats[f"count_{i}"],
                "by_gender": {gender_labels.get(g, g): stats[f"count_{i}_gender_{g}"] for g in genders},
                "by_faculty": {
                    (faculty["faculty__faculty_name"] or "Unspecified"): stats[f"count_{i}_faculty_{faculty['faculty_id']}"]
                    for faculty in faculties
                },
            }
        )
    return rows


def applicant_scores(queryset=None):
    """Per-applicant row data for the Excel export's "Applicant Scores"
    sheet -- not one of the 8 metric groups (it's raw per-row data, not
    an aggregate), but needed alongside them. Evaluated applicants only,
    same as every metric group above. Single query: every column the
    sheet needs (identity, faculty/gender/county, each criterion score,
    evaluator name, evaluation date) comes back in one
    .values().annotate() call, then each row's percentage-of-max is a
    cheap per-row division on already-fetched data -- not a second
    query, and not the database-side computation the "don't loop in
    Python" constraint is actually about (that constraint is for
    statistics like mean/median/stdev, not for formatting a value this
    sheet already fetched for the row it belongs to)."""
    queryset = _evaluated(queryset)
    total_expr = _total_score_expr()

    values_fields = [
        "id",
        "registration_number",
        "first_name",
        "surname",
        "faculty__faculty_name",
        "gender",
        "county_of_residence",
        "score_sheet__evaluator__user__profile__given_name",
        "score_sheet__evaluator__user__profile__family_name",
        "score_sheet__interview_date",
    ] + [f"score_sheet__{name}" for name in SCORE_FIELDS]

    rows = list(queryset.values(*values_fields).annotate(total=total_expr).order_by("surname", "first_name"))

    gender_labels = {value: str(label) for value, label in Gender.choices}
    county_labels = {value: str(label) for value, label in County.choices}

    for row in rows:
        row["name"] = f"{row.pop('first_name')} {row.pop('surname')}".strip()
        row["faculty_name"] = row.pop("faculty__faculty_name") or "Unspecified"
        row["gender_label"] = gender_labels.get(row["gender"], row["gender"])
        row["county_label"] = county_labels.get(row["county_of_residence"], row["county_of_residence"])
        given = row.pop("score_sheet__evaluator__user__profile__given_name") or ""
        family = row.pop("score_sheet__evaluator__user__profile__family_name") or ""
        row["evaluator_name"] = f"{given} {family}".strip() or "Unknown"
        row["evaluation_date"] = row.pop("score_sheet__interview_date")
        row["scores"] = {name: row.pop(f"score_sheet__{name}") for name in SCORE_FIELDS}
        row["percentage_of_max"] = (row["total"] / TOTAL_POSSIBLE * 100) if TOTAL_POSSIBLE else 0.0

    return rows
