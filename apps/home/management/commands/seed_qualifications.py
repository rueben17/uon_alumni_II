# apps/home/management/commands/seed_qualifications.py
"""
Seeds the Qualification catalog from the official UoN 74th Congregation
(December 11, 2025) "Complete List of Programmes Conferred" booklet.
"""
from django.core.management.base import BaseCommand

from apps.home.models import Faculty, Qualification, QualificationLevel

PHD = QualificationLevel.PHD
MASTERS = QualificationLevel.MASTERS
BACHELORS = QualificationLevel.BACHELORS
PGD = QualificationLevel.PGD
DIPLOMA = QualificationLevel.DIPLOMA
FELLOWSHIP = QualificationLevel.FELLOWSHIP

# faculty_name must match apps.home.models.Faculty.faculty_name exactly.
QUALIFICATION_DATA = [
    {
        "faculty_name": "Agriculture",
        "qualifications": [
            (PHD, "PhD in Applied Human Nutrition"),
            (PHD, "PhD in Food Science and Technology"),
            (MASTERS, "MSc in Agronomy"),
            (MASTERS, "MSc in Crop Protection"),
            (MASTERS, "MSc in Food Safety and Quality"),
            (MASTERS, "MSc in Food Science and Technology"),
            (MASTERS, "MSc in Horticulture"),
            (MASTERS, "MSc in Plant Breeding and Biotechnology"),
            (MASTERS, "MSc in Plant Pathology"),
            (MASTERS, "MSc in Agricultural and Applied Economics"),
            (BACHELORS, "BSc in Agribusiness Management"),
            (BACHELORS, "BSc in Agricultural Education and Extension"),
            (BACHELORS, "BSc in Food Science, Nutrition and Dietetics"),
            (BACHELORS, "BSc in Agriculture (Crop Protection Major)"),
            (BACHELORS, "BSc in Agriculture (Crop Science Major)"),
            (BACHELORS, "BSc in Horticulture"),
            (BACHELORS, "BSc in Food Science & Technology"),
            (BACHELORS, "BSc in Management of Agroecosystems and Environment"),
        ],
    },
    {
        "faculty_name": "Arts and Social Sciences",
        "qualifications": [
            (PHD, "PhD in Linguistics"),
            (PHD, "PhD in Kiswahili Studies"),
            (PHD, "PhD in International Studies"),
            (MASTERS, "MA in Economic Policy Management"),
            (MASTERS, "MA in Armed Conflict and Peace Studies"),
            (MASTERS, "MA in Anthropology"),
            (MASTERS, "MA in Diplomacy"),
            (MASTERS, "MA in Gender and Development Studies"),
            (MASTERS, "MA in International Conflict Management"),
            (MASTERS, "MA in International Studies"),
            (MASTERS, "MSc in Population Studies"),
            (MASTERS, "MA in Economics"),
            (MASTERS, "MA in Environmental Planning and Management"),
            (MASTERS, "MA in Biodiversity and Natural Resources Management"),
            (MASTERS, "MA in Communication Studies (Public Relations, Development Communication, Communication Studies)"),
            (MASTERS, "MA in Development Studies"),
            (MASTERS, "MA in History"),
            (MASTERS, "MA in Human Rights"),
            (MASTERS, "MA in International Relations"),
            (MASTERS, "MA in Kiswahili Studies"),
            (MASTERS, "MA in Literature"),
            (MASTERS, "MA in Sociology (Medical Sociology)"),
            (MASTERS, "MA in Monitoring and Evaluation"),
            (MASTERS, "MA in Philosophy"),
            (MASTERS, "MA in Political Science and Public Administration"),
            (MASTERS, "MA in Religious Studies"),
            (MASTERS, "MA in Sociology (Criminology and Social Order)"),
            (MASTERS, "MA in Sociology (Rural Sociology and Community Development)"),
            (MASTERS, "MA in Sociology (Disaster Management)"),
            (MASTERS, "MA in Counseling Psychology"),
            (MASTERS, "MA in Psychology (Industrial and Organizational / Health Psychology)"),
            (MASTERS, "MA in Public Administration"),
            (MASTERS, "MSc in Sustainable Urban Development"),
            (MASTERS, "Masters of Research and Public Policy"),
            (MASTERS, "MSc in Health Economics and Policy"),
            (BACHELORS, "BA in Anthropology"),
            (BACHELORS, "BA in Broadcast Production (Television)"),
            (BACHELORS, "BA in Broadcast Production (Film)"),
            (BACHELORS, "BA in Journalism & Media Studies (Broadcast Journalism)"),
            (BACHELORS, "BA in Journalism & Media Studies (Development Communication)"),
            (BACHELORS, "BA in Journalism & Media Studies (Public Relations)"),
            (BACHELORS, "BA in Economics"),
            (BACHELORS, "BA (General)"),
            (BACHELORS, "BA in Archaeology"),
            (BACHELORS, "BA in Criminology and Criminal Justice"),
            (BACHELORS, "BA in Gender and Development Studies"),
            (BACHELORS, "BA in Literature"),
            (BACHELORS, "BA in Political Science and Public Administration"),
            (BACHELORS, "BA in Sociology"),
            (BACHELORS, "BA in Armed Conflict and Peace Studies"),
            (BACHELORS, "BA in Counselling Psychology"),
            (BACHELORS, "BA in Geography and Environmental Studies"),
            (BACHELORS, "BA in Performing Arts"),
            (BACHELORS, "BA in Psychology"),
            (BACHELORS, "BA in Social Work"),
            (BACHELORS, "BA in Tourism"),
            (BACHELORS, "BA in Hospitality Management (Rooms Division / Food and Beverage)"),
            (BACHELORS, "BA in International Studies"),
            (BACHELORS, "BA in Travel and Tourism Management (Travel Management)"),
            (BACHELORS, "BSc in Economics & Statistics"),
            (BACHELORS, "BSc in Information Science"),
            (PGD, "Postgraduate Diploma in Gender-Based Violence in Emergencies"),
            (PGD, "Postgraduate Diploma in Rural Sociology and Community Development"),
            (DIPLOMA, "Diploma in Criminology and Social Order"),
            (DIPLOMA, "Diploma in International Studies"),
            (DIPLOMA, "Diploma in Psychology"),
            (DIPLOMA, "Diploma in Social Work and Social Development"),
            (DIPLOMA, "Diploma in Women Leadership and Governance in Africa"),
        ],
    },
    {
        "faculty_name": "Built Environment and Design",
        "qualifications": [
            (MASTERS, "MA in Valuation and Property Management"),
            (MASTERS, "MA in Construction Management"),
            (MASTERS, "MA in Design"),
            (BACHELORS, "BA in Design"),
            (BACHELORS, "BA in Interior Design"),
            (BACHELORS, "BA in Architectural Studies"),
            (BACHELORS, "BA in Architecture"),
            (BACHELORS, "BA in Planning"),
            (BACHELORS, "BSc in Construction Management"),
            (BACHELORS, "BSc in Quantity Surveying"),
            (BACHELORS, "BSc in Real Estate"),
        ],
    },
    {
        "faculty_name": "Business & Management Sciences",
        "qualifications": [
            (PHD, "PhD in Business Administration"),
            (PHD, "PhD in Project Planning and Management"),
            (MASTERS, "MA in Project Planning & Management"),
            (MASTERS, "MBA (Master of Business Administration)"),
            (MASTERS, "Master of Business Research"),
            (MASTERS, "MSc in Finance"),
            (MASTERS, "MSc in Human Resource Management"),
            (MASTERS, "MSc in Marketing"),
            (MASTERS, "MSc in Entrepreneurship and Innovations Management"),
            (MASTERS, "MSc in Operations and Technology Management"),
            (MASTERS, "MSc in Supply Chain Management"),
            (BACHELORS, "BCom in Accounting"),
            (BACHELORS, "BCom in Finance"),
            (BACHELORS, "BCom in Marketing"),
            (BACHELORS, "BCom in Insurance"),
            (BACHELORS, "BCom in Human Resource Management"),
            (BACHELORS, "BCom in Procurement and Supply Chain Management"),
            (BACHELORS, "BCom in Business Information Systems"),
            (BACHELORS, "BCom in Operations Management"),
            (BACHELORS, "BSc in Project Planning and Management"),
            (BACHELORS, "BSc in Finance"),
            (PGD, "Postgraduate Diploma in Project Planning and Management"),
            (DIPLOMA, "Diploma in Business Management"),
            (DIPLOMA, "Diploma in Human Resource Management"),
            (DIPLOMA, "Diploma in Project Planning and Management"),
            (DIPLOMA, "Diploma in Public Relations"),
            (DIPLOMA, "Diploma in Purchasing and Supplies Management"),
        ],
    },
    {
        "faculty_name": "Education",
        "qualifications": [
            (PHD, "Doctor of Education (DEd)"),
            (PHD, "PhD in Education"),
            (MASTERS, "MEd (General)"),
            (MASTERS, "MEd in Curriculum Studies"),
            (MASTERS, "MEd in Early Childhood Education"),
            (MASTERS, "MEd in Education in Emergencies"),
            (MASTERS, "MEd in Educational Administration"),
            (MASTERS, "MEd in Educational Planning"),
            (MASTERS, "MEd in Sociology of Education"),
            (MASTERS, "MEd in Educational Technology"),
            (BACHELORS, "BEd (Arts) – Distance Learning"),
            (BACHELORS, "BEd (Science) – Distance Learning"),
            (BACHELORS, "BA in Adult Education and Community Development"),
            (BACHELORS, "BEd (Arts) – Regular"),
            (BACHELORS, "BEd in Early Childhood Education"),
            (BACHELORS, "BEd in Physical Education and Sport"),
            (BACHELORS, "BEd (Science) – Regular"),
            (BACHELORS, "BEd in ICT"),
            (PGD, "Postgraduate Diploma in Education"),
            (DIPLOMA, "Diploma in Adult Education and Community Development"),
        ],
    },
    {
        "faculty_name": "Engineering",
        "qualifications": [
            (PHD, "PhD in Civil Engineering"),
            (PHD, "PhD in Mechanical Engineering"),
            (PHD, "PhD in Nuclear Science"),
            (PHD, "PhD in Environmental and Biosystems Engineering"),
            (PHD, "PhD in Electrical and Electronic Engineering"),
            (MASTERS, "MSc in Civil Engineering"),
            (MASTERS, "MSc in Energy Management"),
            (MASTERS, "MSc in Mechanical Engineering"),
            (MASTERS, "MSc in Civil Engineering (Transportation Engineering)"),
            (MASTERS, "MSc in Electrical and Electronic Engineering"),
            (BACHELORS, "BSc in Civil Engineering"),
            (BACHELORS, "BSc in Electrical and Electronic Engineering"),
            (BACHELORS, "BSc in Mechanical Engineering"),
            (BACHELORS, "BSc in Petroleum Engineering"),
            (BACHELORS, "BSc in Biosystems Engineering"),
            (BACHELORS, "BSc in Geospatial Engineering"),
        ],
    },
    {
        "faculty_name": "Health Sciences",
        "qualifications": [
            (PHD, "PhD in Medicine"),
            (PHD, "PhD in Nursing Sciences"),
            (PHD, "PhD in Infectious Diseases"),
            (PHD, "PhD in Dentistry"),
            (PHD, "PhD in Pharmacology and Therapeutics"),
            (MASTERS, "Master of Dental Surgery in Oral & Maxillofacial Surgery"),
            (MASTERS, "Master of Dental Surgery in Paediatric Dentistry"),
            (MASTERS, "Master of Dental Surgery in Periodontology"),
            (MASTERS, "Master of Dental Surgery in Prosthodontics"),
            (MASTERS, "Master of Medicine in Anaesthesia"),
            (MASTERS, "Master of Medicine in Diagnostic Radiology"),
            (MASTERS, "Master of Medicine in Ear, Nose and Throat Surgery"),
            (MASTERS, "Master of Medicine in General Surgery"),
            (MASTERS, "Master of Medicine in Human Pathology"),
            (MASTERS, "Master of Medicine in Internal Medicine"),
            (MASTERS, "Master of Medicine in Neuro-Surgery"),
            (MASTERS, "Master of Medicine in Obstetrics and Gynaecology"),
            (MASTERS, "Master of Medicine in Ophthalmology"),
            (MASTERS, "Master of Medicine in Orthopaedic Surgery"),
            (MASTERS, "Master of Medicine in Paediatric Surgery"),
            (MASTERS, "Master of Medicine in Paediatrics and Child Health"),
            (MASTERS, "Master of Medicine in Plastic, Reconstructive and Aesthetic Surgery"),
            (MASTERS, "Master of Medicine in Psychiatry"),
            (MASTERS, "Master of Medicine in Radiation Oncology"),
            (MASTERS, "Master of Medicine in Thoracic and Cardiovascular Surgery"),
            (MASTERS, "Master of Medicine in Urology"),
            (MASTERS, "Master of Pharmacy in Clinical Pharmacy"),
            (MASTERS, "Master of Pharmacy in Pharmacoepidemiology and Pharmacovigilance"),
            (MASTERS, "Master of Public Health"),
            (MASTERS, "MSc in Clinical Cytology"),
            (MASTERS, "MSc in Clinical Psychology"),
            (MASTERS, "MSc in Medical Statistics"),
            (MASTERS, "MSc in Molecular Pharmacology"),
            (MASTERS, "MSc in Nursing (Critical Care Nursing)"),
            (MASTERS, "MSc in Nursing (Obstetrics Nursing/Midwifery)"),
            (MASTERS, "MSc in Nursing (Oncology Nursing)"),
            (MASTERS, "MSc in Nursing (Paediatric Nursing)"),
            (MASTERS, "MSc in Tropical & Infectious Diseases"),
            (MASTERS, "MSc in Renal Nursing"),
            (MASTERS, "MSc in Nursing (Mental Health and Psychiatric Nursing)"),
            (BACHELORS, "BSc in Nursing"),
            (BACHELORS, "BSc in Medical Laboratory Science and Technology"),
            (BACHELORS, "BSc in Human Anatomy"),
            (BACHELORS, "BSc in Medical Physiology"),
            (BACHELORS, "Bachelor of Dental Surgery (BDS)"),
            (BACHELORS, "Bachelor of Medicine and Bachelor of Surgery (MBChB)"),
            (BACHELORS, "Bachelor of Pharmacy"),
            (FELLOWSHIP, "Fellowship in Paediatric and Adolescent Endocrinology"),
            (FELLOWSHIP, "Fellowship of Clinical Infectious Disease"),
            (FELLOWSHIP, "Fellowship in Gynaecological Oncology"),
            (FELLOWSHIP, "Fellowship in Paediatric Nephrology"),
            (FELLOWSHIP, "Fellowship in Paediatric Anaesthesia"),
            (DIPLOMA, "Diploma in Renal Nursing"),
        ],
    },
    {
        "faculty_name": "Law",
        "qualifications": [
            (PHD, "PhD in Law"),
            (PHD, "PhD in Environmental Policy"),
            (MASTERS, "MA in Environmental Law"),
            (MASTERS, "MA in Environmental Policy"),
            (MASTERS, "MA in Women, Children and Nature Rights in Environmental Governance"),
            (MASTERS, "Master of Laws (LLM)"),
            (BACHELORS, "Bachelor of Laws (LLB)"),
        ],
    },
    {
        "faculty_name": "Science and Technology",
        "qualifications": [
            (PHD, "PhD in Microbiology"),
            (PHD, "PhD in Biological Science"),
            (PHD, "PhD in Geology"),
            (PHD, "PhD in Physics"),
            (PHD, "PhD in Climate Change and Adaptation"),
            (MASTERS, "MSc in Information Technology Management"),
            (MASTERS, "MSc in Climate Change Adaptation"),
            (MASTERS, "MSc in Actuarial Science"),
            (MASTERS, "MSc in Agricultural Entomology"),
            (MASTERS, "MSc in Biochemistry"),
            (MASTERS, "MSc in Bioinformatics"),
            (MASTERS, "MSc in Biometry"),
            (MASTERS, "MSc in Climate Change"),
            (MASTERS, "MSc in Data Science"),
            (MASTERS, "MSc in Environmental Chemistry"),
            (MASTERS, "MSc in Environmental Governance"),
            (MASTERS, "MSc in Geology"),
            (MASTERS, "MSc in Geology (Engineering Geology)"),
            (MASTERS, "MSc in Hydrobiology (Aquaculture)"),
            (MASTERS, "MSc in Industrial Chemistry"),
            (MASTERS, "MSc in Meteorology"),
            (MASTERS, "MSc in Social Statistics"),
            (MASTERS, "MSc in Statistics"),
            (BACHELORS, "BSc (General)"),
            (BACHELORS, "BSc in Chemistry"),
            (BACHELORS, "BSc in Actuarial Science"),
            (BACHELORS, "BSc in Analytical Chemistry"),
            (BACHELORS, "BSc in Astronomy and Astrophysics"),
            (BACHELORS, "BSc in Biology"),
            (BACHELORS, "BSc in Environmental Conservation and Natural Resources Management"),
            (BACHELORS, "BSc in Geology"),
            (BACHELORS, "BSc in Industrial Chemistry"),
            (BACHELORS, "BSc in Mathematics"),
            (BACHELORS, "BSc in Meteorology"),
            (BACHELORS, "BSc in Microbiology and Biotechnology"),
            (BACHELORS, "BSc in Microprocessor Technology & Instrumentation"),
            (BACHELORS, "BSc in Petroleum Geoscience"),
            (BACHELORS, "BSc in Statistics"),
            (BACHELORS, "BSc in Computer Science"),
            (DIPLOMA, "Diploma in Computer Science"),
        ],
    },
    {
        "faculty_name": "Veterinary Medicine",
        "qualifications": [
            (PHD, "PhD in Veterinary Public Health"),
            (MASTERS, "MSc in Fish Science"),
            (MASTERS, "MSc in One Health and Emergency Research Ethics"),
            (MASTERS, "MSc in Reproductive Biology"),
            (MASTERS, "MSc in Veterinary Epidemiology & Economics"),
            (MASTERS, "MSc in Veterinary Pathology and Diagnostics"),
            (MASTERS, "MSc in Veterinary Pathology, Microbiology and Parasitology"),
            (BACHELORS, "BSc in Wildlife Management and Conservation"),
            (BACHELORS, "Bachelor of Veterinary Medicine (BVM)"),
            (BACHELORS, "BSc in Leather Science and Technology"),
        ],
    },
    {
        "faculty_name": "Koitaleel Samoei University College",
        "qualifications": [
            (MASTERS, "Master of Business Administration (MBA)"),
            (BACHELORS, "Bachelor of Education (Arts)"),
            (MASTERS, "Master of Education (MEd)"),
        ],
    },
    {
        # Constituent college, not yet chartered -- confers UoN degrees
        # under supervision (same category as Koitaleel Samoei above; see
        # docs/uon_faculty_mapping.json's "constituent_colleges" section).
        # No qualifications listed here yet -- none appeared in the 74th
        # Congregation booklet this command sources from, but the Faculty
        # row needs to exist so alumni records citing it resolve correctly.
        "faculty_name": "Nyandarua University College",
        "qualifications": [],
    },
]


class Command(BaseCommand):
    help = "Populate the Qualification catalog from the official UoN congregation booklet"

    def handle(self, *args, **options):
        faculties_created = 0
        qualifications_created = 0

        for entry in QUALIFICATION_DATA:
            faculty, created = Faculty.objects.get_or_create(
                faculty_name=entry["faculty_name"]
            )
            if created:
                faculties_created += 1
                self.stdout.write(f"  Created faculty: {faculty.faculty_name}")

            for level, name in entry["qualifications"]:
                qualification, qual_created = Qualification.objects.get_or_create(
                    faculty=faculty,
                    name=name,
                    defaults={"level": level},
                )
                if qual_created:
                    qualifications_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {faculties_created} faculties created, "
                f"{qualifications_created} qualifications created."
            )
        )
