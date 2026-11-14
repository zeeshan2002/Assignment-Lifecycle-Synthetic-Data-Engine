"""
Master data: Staff, Course, CourseStaff (bridge), Learner, Enrollment (bridge).

Dependencies are respected: learners are registered before their first enrolment, enrolments start
inside a course's enrolment window, and drops/completions carry an effective-to date.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from src.config import ScaleConfig, SNAPSHOT_AT
from src.generator.prng import SeededRNG
from src.id_generator import IdGenerator
from src.schema import DEPARTMENTS, TERMS
from src.timeutil import fmt, parse

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Sam", "Chris", "Pat", "Avery", "Riley", "Cameron", "Dakota",
    "Reese", "Quinn", "Skyler", "Jesse", "Casey", "Jamie", "Logan", "Kendall", "Harper", "Peyton",
    "Rowan", "Eden", "Finley", "Emerson", "River", "Hayden", "Sawyer", "Kai", "Amara", "Zubair", "Chen",
    "Priya", "Carlos", "Fatima", "Liam", "Noah", "Emma", "Olivia", "Sophia", "Lucas", "Mateo", "Aarav", "Mei",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Khan",
    "Patel", "Sharma", "Tanaka", "Kim",
]
DEPT_COURSES = {
    "Computer Science": ("CS", ["Intro to Programming", "Data Structures & Algorithms", "Operating Systems",
                               "Computer Networks", "Database Management Systems", "Artificial Intelligence"]),
    "Data Science": ("DS", ["Principles of Data Science", "Applied Machine Learning", "Data Mining",
                            "Big Data Analytics", "Deep Learning", "Natural Language Processing"]),
    "Mathematics": ("MATH", ["Calculus I", "Linear Algebra", "Probability & Statistics", "Discrete Mathematics",
                             "Numerical Optimization"]),
    "Engineering": ("ENG", ["Digital Logic Design", "Microprocessor Systems", "Signal Processing", "Control Systems",
                            "Embedded Systems"]),
    "Business": ("BUS", ["Management Information Systems", "Business Analytics", "Technology Entrepreneurship"]),
}
TERM_BASE = {  # (month, day, max start jitter in days)
    "SPRING-2026": (1, 12, 14), "SUMMER-2026": (5, 4, 14), "FALL-2026": (9, 7, 35),   # late FALL courses are still running at the cut-off
}
TERM_WEIGHTS = (0.45, 0.25, 0.30)  # SPRING, SUMMER, FALL
COURSE_LENGTH_DAYS = 60
COURSE_TZ_CHOICES = ["UTC", "America/New_York", "Asia/Kolkata", "Europe/London", "America/Los_Angeles"]
TZ_WEIGHTS = (0.15, 0.30, 0.20, 0.15, 0.20)


class MasterDataGenerator:
    def __init__(self, rng: SeededRNG, ids: IdGenerator, scale: ScaleConfig):
        self.rng, self.ids, self.scale = rng, ids, scale
        self.course_tz: Dict[str, str] = {}

    # ---- staff ----
    def generate_staff(self) -> List[dict]:
        rows = []
        spec = [("INSTRUCTOR", "INS", self.scale.num_instructors), ("ACADEMIC_ADMIN", "ADM", self.scale.num_admins),
                ("SUPPORT_STAFF", "SUP", self.scale.num_support), ("PLATFORM_ADMIN", "PLT", self.scale.num_platform)]
        for role, prefix, n in spec:
            for i in range(1, n + 1):
                r = self.rng.spawn("staff", prefix, i)
                first, last = r.choice(FIRST_NAMES), r.choice(LAST_NAMES)
                hired = datetime(2015, 1, 1, tzinfo=timezone.utc) + timedelta(days=r.randint(0, 3600), hours=r.randint(0, 23))
                rows.append({
                    "staff_id": self.ids.staff_id(prefix, i),
                    "full_name": f"{first} {last}",
                    "email": f"{first}.{last}.{prefix}{i:03d}@staff.univ.edu".lower(),
                    "role": role,
                    "department": DEPARTMENTS[(i - 1) % len(DEPARTMENTS)] if role == "INSTRUCTOR" else None,
                    # a few instructors are inactive and therefore never assigned to anything
                    "status": "INACTIVE" if (role == "INSTRUCTOR" and i > 6 and r.random() < 0.04) else "ACTIVE",
                    "hired_at_utc": fmt(hired),
                })
        return rows

    # ---- courses + bridge ----
    def generate_courses(self, staff: List[dict]) -> Tuple[List[dict], List[dict]]:
        instructors = [s for s in staff if s["role"] == "INSTRUCTOR" and s["status"] == "ACTIVE"]
        platform = [s for s in staff if s["role"] == "PLATFORM_ADMIN"]
        by_dept: Dict[str, List[dict]] = {}
        for s in instructors:
            by_dept.setdefault(s["department"], []).append(s)
        courses, bridge = [], []
        csf = 1
        for i in range(1, self.scale.num_courses + 1):
            r = self.rng.spawn("course", i)
            dept = r.choice(DEPARTMENTS)
            prefix, titles = DEPT_COURSES[dept]
            term = r.choices(TERMS, weights=TERM_WEIGHTS, k=1)[0]
            m, d, jit = TERM_BASE[term]
            start = datetime(2026, m, d, 8, 0, tzinfo=timezone.utc) + timedelta(days=r.randint(0, jit))
            end = start + timedelta(days=COURSE_LENGTH_DAYS)
            created = start - timedelta(days=r.randint(30, 75), hours=r.randint(0, 8))
            pool = by_dept.get(dept) or instructors
            lead = r.choice(pool)
            others = [s for s in instructors if s["staff_id"] != lead["staff_id"]]
            graders = r.sample(others, k=min(len(others), r.randint(1, 2)))
            cid = self.ids.course_id(i)
            courses.append({
                "course_id": cid,
                "course_code": f"{prefix}{r.choice([101, 201, 301, 401])}-{i:03d}",
                "title": f"{r.choice(titles)} (Section {i % 5 + 1})",
                "department": dept, "term": term,
                "instructor_id": lead["staff_id"],
                "created_by": r.choice(platform)["staff_id"],
                "created_at_utc": fmt(created), "start_date_utc": fmt(start), "end_date_utc": fmt(end),
            })
            self.course_tz[cid] = r.choices(COURSE_TZ_CHOICES, weights=TZ_WEIGHTS, k=1)[0]
            for role, person in [("LEAD_INSTRUCTOR", lead)] + [("GRADER", g) for g in graders]:
                bridge.append({
                    "course_staff_id": self.ids.course_staff_id(csf), "course_id": cid, "staff_id": person["staff_id"],
                    "course_role": role, "effective_from_utc": fmt(start - timedelta(days=7)), "effective_to_utc": None,
                })
                csf += 1
        return courses, bridge

    # ---- learners + enrolments ----
    def generate_learners_and_enrollments(self, courses: List[dict], staff: List[dict]) -> Tuple[List[dict], List[dict]]:
        support = [s for s in staff if s["role"] == "SUPPORT_STAFF" and s["status"] == "ACTIVE"]
        course_ids = [c["course_id"] for c in courses]
        cmap = {c["course_id"]: c for c in courses}
        learners, enrollments = [], []
        enr_no = 1
        for i in range(1, self.scale.num_learners + 1):
            r = self.rng.spawn("learner-master", i)
            first, last = r.choice(FIRST_NAMES), r.choice(LAST_NAMES)
            k = r.choices([1, 2, 3], weights=self.scale.enroll_weights, k=1)[0]
            picks = r.sample(course_ids, k=min(k, len(course_ids)))
            first_enr, last_enr = None, None
            for cid in picks:
                c = cmap[cid]
                start, end = parse(c["start_date_utc"]), parse(c["end_date_utc"])
                enrolled = start - timedelta(days=14) + timedelta(seconds=r.randint(0, 28 * 86400))
                roll = r.random()
                eff_to, status = None, "ENROLLED"
                if roll < 0.03:
                    status = "AUDIT"
                elif roll < 0.10:
                    dropped_at = min(enrolled + timedelta(days=r.randint(8, 35), hours=r.randint(0, 23)), end - timedelta(days=5))
                    dropped_at = max(dropped_at, enrolled + timedelta(days=3))
                    if dropped_at <= SNAPSHOT_AT:          # a drop after the data cut-off has not happened yet
                        status, eff_to = "DROPPED", dropped_at
                if status != "DROPPED" and end <= SNAPSHOT_AT:
                    if status == "ENROLLED":
                        status, eff_to = "COMPLETED", end
                enrollments.append({
                    "enrollment_id": self.ids.enrollment_id(enr_no), "course_id": cid, "learner_id": self.ids.learner_id(i),
                    "enrolled_at_utc": fmt(enrolled), "effective_to_utc": fmt(eff_to) if eff_to else None,
                    "enrollment_status": status, "processed_by": r.choice(support)["staff_id"],
                })
                enr_no += 1
                first_enr = enrolled if first_enr is None else min(first_enr, enrolled)
                last_enr = enrolled if last_enr is None else max(last_enr, enrolled)
            reg = first_enr - timedelta(days=r.randint(2, 90), hours=r.randint(0, 23))
            roll = r.random()
            status, eff = "ACTIVE", None
            if roll >= 0.94:
                status = "SUSPENDED" if roll < 0.98 else "ALUMNI"
                eff_dt = last_enr + timedelta(days=r.randint(10, 100))
                if eff_dt > SNAPSHOT_AT:
                    eff_dt = SNAPSHOT_AT - timedelta(days=r.randint(1, 10))
                eff = fmt(eff_dt)
            learners.append({
                "learner_id": self.ids.learner_id(i), "first_name": first, "last_name": last,
                "email": f"{first}.{last}{i:06d}@univ.edu".lower(),
                "registration_date_utc": fmt(reg), "status": status, "status_effective_from_utc": eff,
            })
        return learners, enrollments
