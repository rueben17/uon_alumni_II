# staff/management/commands/seed_university_structure.py
from django.core.management.base import BaseCommand
from apps.staff.models import Faculty, Department, ServiceUnit, ResearchUnit

# -------------------------------------------------------------------
# 1. ACADEMIC FACULTIES AND DEPARTMENTS (UoN official)
# -------------------------------------------------------------------
ACADEMIC_DATA = [
    {
        "faculty_name": "Agriculture",
        "departments": [
            "Agricultural Economics",
            "Food Science, Nutrition & Technology",
            "Land Resource Management & Agricultural Technology",
            "Plant Science & Crop Protection",
        ],
    },
    {
        "faculty_name": "Arts and Social Sciences",
        "departments": [
            "Linguistics and Languages",
            "Philosophy and Religious Studies",
            "Library and Information Science",
            "History and Archeology",
            "Economics and Development Studies",
            "Sociology, Social Work and African Women Studies",
            "Political Science and Public Administration",
            "Anthropology, Gender and African Studies",
            "Journalism & Mass Communication",
            "Diplomacy and International Studies",
            "Literature",
            "Kiswahili",
            "Geography, Population and Environmental Studies",
            "Psychology",
        ],
    },
    {
        "faculty_name": "Built Environment and Design",
        "departments": [
            "Art and Design",
            "Architecture",
            "Real Estate, Construction Management & Quantity Surveying",
            "Urban and Regional Planning",
        ],
    },
    {
        "faculty_name": "Business & Management Sciences",
        "departments": [
            "Business Administration",
            "Finance and Accounting",
            "Management Science and Project Planning",
        ],
    },
    {
        "faculty_name": "Education",
        "departments": [
            "Educational Management, Policy and Curriculum Studies",
            "Educational Communication and Pedagogical Studies",
            "Physical Education and Sport",
            "Educational Foundations",
            "Educational and Distance Studies",
        ],
    },
    {
        "faculty_name": "Engineering",
        "departments": [
            "Mechanical Engineering",
            "Civil and Construction Engineering",
            "Electrical and Information Engineering",
            "Environmental and Biosystems Engineering",
            "Geospatial and Space Technology",
        ],
    },
    {
        "faculty_name": "Law",
        "departments": ["Law"],
    },
    {
        "faculty_name": "Health Sciences",
        "departments": [
            "Dental Sciences",
            "Nursing Sciences",
            "Public and Global Health",
            "Surgery",
            "Human Anatomy and Physiology",
            "Clinical Medicine and Therapeutics",
            "Pediatrics and Child Health",
            "Obstetrics and Gynecology",
            "Ophthalmology",
            "Human Pathology",
            "Psychiatry",
            "Diagnostic Imaging and Radiation Medicine",
            "Medical Microbiology and Immunology",
            "Pharmacy",
        ],
    },
    {
        "faculty_name": "Science and Technology",
        "departments": [
            "Chemistry",
            "Computing and Informatics",
            "Mathematics",
            "Physics",
            "Biology",
            "Earth and Climate Sciences",
            "Biochemistry",
        ],
    },
    {
        "faculty_name": "Veterinary Medicine",
        "departments": [
            "Public Health, Pharmacology and Toxicology",
            "Veterinary Anatomy and Physiology",
            "Animal Production",
            "Clinical Studies",
            "Veterinary Pathology, Microbiology and Parasitology",
        ],
    },
]

# -------------------------------------------------------------------
# 2. SERVICE UNITS (Offices, Directorates, Administrative)
# -------------------------------------------------------------------
SERVICE_DATA = [
    {"name": "Academics", "unit_type": "OFFICE"},
    {"name": "Administration", "unit_type": "OFFICE"},
    {"name": "Board of Common Undergraduate Courses", "unit_type": "BOARD"},
    {"name": "Centre for International Programmes and Links", "unit_type": "CENTRE"},
    {"name": "Centre for Self Sponsored Programmes (CESSP)", "unit_type": "CENTRE"},
    {"name": "Construction & Maintenance", "unit_type": "OTHER"},
    {"name": "Customer Experience & Information Centre", "unit_type": "CENTRE"},
    {"name": "Dean of Students", "unit_type": "OFFICE"},
    {"name": "Directorate of Corporate Affairs", "unit_type": "DIRECTORATE"},
    {"name": "Directorate of University Advancement", "unit_type": "DIRECTORATE"},
    {"name": "Estates", "unit_type": "OTHER"},
    {"name": "Finance", "unit_type": "OFFICE"},
    {"name": "Graduate School (GS)", "unit_type": "DIRECTORATE"},
    {"name": "Information, Communication & Technology Center (ICT)", "unit_type": "CENTRE"},
    {"name": "Intellectual Property Management Office (IPMO)", "unit_type": "OFFICE"},
    {"name": "Internal Audit", "unit_type": "OFFICE"},
    {"name": "Legal Office", "unit_type": "OFFICE"},
    {"name": "Office of Career Services", "unit_type": "OFFICE"},
    {"name": "Planning", "unit_type": "OFFICE"},
    {"name": "Procurement", "unit_type": "OFFICE"},
    {"name": "Quality Assurance", "unit_type": "OFFICE"},
    {"name": "Security", "unit_type": "OTHER"},
    {"name": "Sports & Games", "unit_type": "OTHER"},
    {"name": "Student Welfare Authority", "unit_type": "OTHER"},
    {"name": "Transport", "unit_type": "OTHER"},
    {"name": "University Health Services", "unit_type": "CENTRE"},
    {"name": "University Library", "unit_type": "CENTRE"},
    {"name": "University Press", "unit_type": "OTHER"},
]

# -------------------------------------------------------------------
# 3. RESEARCH UNITS (Institutes and Centres)
# -------------------------------------------------------------------
RESEARCH_DATA = [
    {"name": "Wangari Maathai Institute for Peace and Environmental Studies", "unit_type": "INSTITUTE"},
    {"name": "Institute of Nuclear Science & Technology", "unit_type": "INSTITUTE"},
    {"name": "Institute for Climate Change & Adaptation", "unit_type": "INSTITUTE"},
    {"name": "KAVI Institute of Clinical Research", "unit_type": "INSTITUTE"},
    {"name": "Institute of Anthropology, Gender & African Studies", "unit_type": "INSTITUTE"},
    {"name": "University of Nairobi Institute of Tropical and Infectious Diseases (UNITID)", "unit_type": "INSTITUTE"},
    {"name": "East African Kidney Institute", "unit_type": "INSTITUTE"},
    {"name": "Population Studies and Research Institute (PSRI)", "unit_type": "INSTITUTE"},
    {"name": "Institute of Diplomacy and International Studies", "unit_type": "INSTITUTE"},
    {"name": "Institute for Development Studies (IDS)", "unit_type": "INSTITUTE"},
    {"name": "Confucius Institute", "unit_type": "INSTITUTE"},
    {"name": "Center for Epidemiological Modelling and Analysis (CEMA)", "unit_type": "CENTRE"},
    {"name": "African Women's Studies Centre", "unit_type": "CENTRE"},
    {"name": "Centre for Bioinformatics and Biotechnology (CEBIB)", "unit_type": "CENTRE"},
    {"name": "Centre for Environmental Law and Policy (CASELAP)", "unit_type": "CENTRE"},
    {"name": "Centre for Pedagogy and Andragogy (CEPA)", "unit_type": "CENTRE"},
    {"name": "Centre for Translation and Interpretation", "unit_type": "CENTRE"},
    {"name": "University of Nairobi Clinical Research Centre (UNCRC)", "unit_type": "CENTRE"},
]

# -------------------------------------------------------------------
# MANAGEMENT COMMAND
# -------------------------------------------------------------------
class Command(BaseCommand):
    help = "Populate Faculty, Department, ServiceUnit, and ResearchUnit models with UoN data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear all existing records before populating",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            Department.objects.all().delete()
            Faculty.objects.all().delete()
            ServiceUnit.objects.all().delete()
            ResearchUnit.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared all existing records."))

        # ---------- FACULTIES & DEPARTMENTS ----------
        faculties_created = 0
        departments_created = 0

        for faculty_data in ACADEMIC_DATA:
            faculty, created = Faculty.objects.get_or_create(
                faculty_name=faculty_data["faculty_name"]
            )
            if created:
                faculties_created += 1
                self.stdout.write(f"  Created faculty: {faculty.faculty_name}")

            for dept_name in faculty_data["departments"]:
                dept, dept_created = Department.objects.get_or_create(
                    name=dept_name,
                    faculty=faculty,
                )
                if dept_created:
                    departments_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Academic: {faculties_created} faculties, {departments_created} departments created."
            )
        )

        # ---------- SERVICE UNITS ----------
        service_created = 0
        for item in SERVICE_DATA:
            unit, created = ServiceUnit.objects.get_or_create(
                name=item["name"],
                defaults={"unit_type": item.get("unit_type")}
            )
            if created:
                service_created += 1
                self.stdout.write(f"  Created service unit: {unit.name}")

        self.stdout.write(
            self.style.SUCCESS(f"✓ Service: {service_created} units created.")
        )

        # ---------- RESEARCH UNITS ----------
        research_created = 0
        for item in RESEARCH_DATA:
            unit, created = ResearchUnit.objects.get_or_create(
                name=item["name"],
                defaults={"unit_type": item.get("unit_type")}
            )
            if created:
                research_created += 1
                self.stdout.write(f"  Created research unit: {unit.name}")

        self.stdout.write(
            self.style.SUCCESS(f"✓ Research: {research_created} units created.\nDone.")
        )