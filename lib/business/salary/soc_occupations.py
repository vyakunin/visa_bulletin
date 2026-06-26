"""Curated occupation registry for the {occupation} H-1B/PERM salary landing pages.

Why a curated registry instead of the existing job-title clusters: the cluster
canonical_title is derived from messy employer-typed `job_title` strings, so the
highest-demand head terms get mangled (e.g. /job-title/software-engineer/ 301s to
"sr-member-of-the-technical-staff-software-engineer"). The result is that the
existing /job-title/ pages only ever rank for ultra-long-tail niche titles, while
the head-term demand ("software engineer h1b salary", "data scientist salary")
has no clean landing page.

DOL assigns every LCA/PERM filing a Standard Occupational Classification (SOC)
code — clean, standardized, and stable across employers. We key occupation pages
off the SOC code (NOT the garbage employer-typed `soc_title`, which is frequently
just the code itself or a random job title), and supply the human-readable
occupation name + colloquial aliases here.

Each occupation matches one or more SOC-6 prefixes via `soc_code__startswith`.
Raw codes appear as "15-1252", "15-1252.00", or occasionally "15-1252.01 ..." —
the dashed 7-char prefix reliably catches every variant of a SOC-6 code. SOC code
identities were validated against the dominant real `job_title` per code on prod
(FY>=2023), so the groupings reflect what employers actually file under each code,
including 2010<->2018 SOC version drift (e.g. Data Scientists historically filed
under 15-2041 Statisticians before the 2018 15-2051 code existed).
"""

from dataclasses import dataclass, field

from django.db.models import Q
from django.utils.text import slugify


@dataclass(frozen=True)
class Occupation:
    """A curated occupation that aggregates one or more SOC-6 codes.

    slug: stable URL slug (/h1b-salary/<slug>/). Never derived at runtime.
    display: human occupation name used in <h1>, <title>, and prose.
    soc6: dashed 7-char SOC-6 prefixes matched via soc_code__startswith.
    aliases: alternative slugs that 301-redirect to `slug` (colloquial search
        terms + SOC-version spellings), so /h1b-salary/swe/ reaches the canonical.
    blurb: one-line occupation description for the intro paragraph + meta.
    """

    slug: str
    display: str
    soc6: tuple[str, ...]
    aliases: tuple[str, ...] = field(default_factory=tuple)
    blurb: str = ""

    def soc_q(self) -> Q:
        """OR of soc_code__startswith over every SOC-6 prefix for this occupation."""
        q = Q()
        for prefix in self.soc6:
            q |= Q(soc_code__startswith=prefix)
        return q


# Ordered by category then rough filing volume. Display names are the colloquial
# head term people actually search ("Software Engineer"), not the bureaucratic SOC
# title ("Software Developers"). soc6 groupings validated against prod data.
OCCUPATIONS: tuple[Occupation, ...] = (
    # ---- Software & IT ----
    Occupation(
        "software-engineer", "Software Engineer",
        ("15-1252", "15-1132", "15-1133", "15-1131"),
        ("software-developer", "swe", "sde", "software-development-engineer"),
        "Software engineers design, build, and maintain software applications and "
        "systems — by far the largest occupation in H-1B visa sponsorship.",
    ),
    Occupation(
        "qa-engineer", "QA / Software Test Engineer",
        ("15-1253",),
        ("software-tester", "test-engineer", "sdet", "quality-assurance-engineer"),
        "Software QA and test engineers design test plans and automation to verify "
        "software quality before release.",
    ),
    Occupation(
        "data-scientist", "Data Scientist",
        ("15-2051", "15-2041"),
        ("data-science", "machine-learning-engineer", "ml-engineer"),
        "Data scientists apply statistics and machine learning to extract insight "
        "from data — a fast-growing H-1B occupation.",
    ),
    Occupation(
        "data-engineer", "Data Engineer",
        ("15-1243",),
        ("database-architect", "big-data-engineer"),
        "Data engineers build and operate the data pipelines and warehouses that "
        "power analytics and machine learning.",
    ),
    Occupation(
        "database-administrator", "Database Administrator",
        ("15-1242",),
        ("dba",),
        "Database administrators install, configure, and tune database systems for "
        "performance, reliability, and security.",
    ),
    Occupation(
        "systems-analyst", "Computer Systems Analyst",
        ("15-1211", "15-1121"),
        ("computer-systems-analyst", "it-analyst"),
        "Computer systems analysts study an organization's systems and procedures "
        "and design IT solutions to improve efficiency.",
    ),
    Occupation(
        "network-engineer", "Network Engineer",
        ("15-1244", "15-1143"),
        ("network-administrator", "network-and-computer-systems-administrator"),
        "Network and computer systems administrators design, install, and maintain "
        "an organization's networks and servers.",
    ),
    Occupation(
        "security-engineer", "Information Security Analyst",
        ("15-1212", "15-1122"),
        ("information-security-analyst", "cybersecurity-engineer", "security-analyst"),
        "Information security analysts protect an organization's networks and data "
        "from cyber threats.",
    ),
    Occupation(
        "web-developer", "Web Developer",
        ("15-1254", "15-1134", "15-1255"),
        ("web-designer", "front-end-developer", "ui-developer"),
        "Web developers build and maintain websites and web applications.",
    ),
    # ---- Engineering ----
    Occupation(
        "mechanical-engineer", "Mechanical Engineer",
        ("17-2141",),
        ("mech-engineer",),
        "Mechanical engineers design, develop, and test mechanical and thermal "
        "devices, machines, and systems.",
    ),
    Occupation(
        "electrical-engineer", "Electrical & Electronics Engineer",
        ("17-2071", "17-2072"),
        ("electronics-engineer", "ee", "hardware-engineer-electrical"),
        "Electrical and electronics engineers design and develop electrical "
        "equipment, circuits, and electronic systems.",
    ),
    Occupation(
        "industrial-engineer", "Industrial Engineer",
        ("17-2112",),
        ("manufacturing-engineer", "process-engineer-industrial"),
        "Industrial engineers design efficient systems that integrate workers, "
        "machines, materials, and processes.",
    ),
    Occupation(
        "civil-engineer", "Civil Engineer",
        ("17-2051",),
        (),
        "Civil engineers design and oversee construction of infrastructure such as "
        "roads, bridges, and buildings.",
    ),
    Occupation(
        "computer-hardware-engineer", "Computer Hardware Engineer",
        ("17-2061",),
        ("hardware-engineer",),
        "Computer hardware engineers research, design, and test computer systems "
        "and components such as processors and circuit boards.",
    ),
    Occupation(
        "sales-engineer", "Sales Engineer",
        ("41-9031",),
        (),
        "Sales engineers sell complex scientific and technological products to "
        "businesses, combining technical and sales expertise.",
    ),
    # ---- Finance & Business ----
    Occupation(
        "financial-analyst", "Financial Analyst",
        ("13-2051",),
        ("investment-analyst", "finance-analyst"),
        "Financial and investment analysts evaluate investments and guide business "
        "and individual financial decisions.",
    ),
    Occupation(
        "accountant", "Accountant",
        ("13-2011",),
        ("auditor", "accountant-and-auditor"),
        "Accountants and auditors prepare and examine financial records to ensure "
        "accuracy and regulatory compliance.",
    ),
    Occupation(
        "management-consultant", "Management Consultant",
        ("13-1111",),
        ("management-analyst", "consultant", "business-consultant"),
        "Management analysts (consultants) advise organizations on how to improve "
        "efficiency and profitability.",
    ),
    Occupation(
        "business-analyst", "Business / Operations Research Analyst",
        ("15-2031",),
        ("operations-research-analyst", "business-systems-analyst"),
        "Operations research analysts use advanced analytical methods to help "
        "organizations solve problems and make better decisions.",
    ),
    Occupation(
        "market-research-analyst", "Market Research Analyst",
        ("13-1161",),
        ("marketing-specialist", "marketing-analyst"),
        "Market research analysts study market conditions to assess the potential "
        "sales of products and services.",
    ),
    Occupation(
        "financial-manager", "Financial Manager",
        ("11-3031",),
        ("finance-manager", "cfo", "controller"),
        "Financial managers direct an organization's financial health — planning, "
        "reporting, and investment strategy.",
    ),
    Occupation(
        "quantitative-analyst", "Quantitative Analyst",
        ("13-2099",),
        ("quant", "quantitative-researcher"),
        "Quantitative analysts apply mathematical and statistical models to "
        "financial and trading problems.",
    ),
    Occupation(
        "logistician", "Logistician / Supply Chain Analyst",
        ("13-1081",),
        ("logistics-analyst", "supply-chain-analyst"),
        "Logisticians analyze and coordinate an organization's supply chain — the "
        "movement of products from supplier to consumer.",
    ),
    # ---- Management ----
    Occupation(
        "it-manager", "Computer & Information Systems Manager",
        ("11-3021",),
        ("engineering-manager-it", "technology-manager", "it-director"),
        "Computer and information systems managers plan and direct an "
        "organization's technology strategy and teams.",
    ),
    Occupation(
        "engineering-manager", "Architectural & Engineering Manager",
        ("11-9041",),
        ("engineering-director",),
        "Architectural and engineering managers plan and direct activities in "
        "engineering and architecture organizations.",
    ),
    Occupation(
        "operations-manager", "General & Operations Manager",
        ("11-1021",),
        ("general-manager", "operations-director"),
        "General and operations managers oversee the daily operations of "
        "businesses across many industries.",
    ),
    Occupation(
        "marketing-manager", "Marketing Manager",
        ("11-2021",),
        (),
        "Marketing managers plan and direct programs to generate interest in a "
        "company's products or services.",
    ),
    Occupation(
        "sales-manager", "Sales Manager",
        ("11-2022",),
        (),
        "Sales managers direct an organization's sales teams, set goals, and "
        "analyze sales data.",
    ),
    Occupation(
        "project-manager", "Project Management Specialist",
        ("13-1082",),
        ("project-management-specialist", "program-manager"),
        "Project management specialists coordinate the budget, schedule, and "
        "resources to deliver projects on time.",
    ),
    Occupation(
        "chief-executive", "Chief Executive",
        ("11-1011",),
        ("ceo", "executive"),
        "Chief executives determine and direct the strategy and policies of "
        "organizations at the highest level.",
    ),
    # ---- Healthcare ----
    Occupation(
        "medical-technologist", "Medical & Clinical Laboratory Technologist",
        ("29-2011",),
        ("clinical-laboratory-scientist", "medical-laboratory-scientist", "medical-technologist"),
        "Medical and clinical laboratory technologists perform complex tests that "
        "help diagnose and treat disease.",
    ),
    Occupation(
        "registered-nurse", "Registered Nurse",
        ("29-1141",),
        ("rn", "nurse"),
        "Registered nurses provide and coordinate patient care across hospitals, "
        "clinics, and other healthcare settings.",
    ),
    Occupation(
        "physical-therapist", "Physical Therapist",
        ("29-1123",),
        ("pt",),
        "Physical therapists help injured or ill patients improve movement and "
        "manage pain through rehabilitation.",
    ),
    Occupation(
        "physician", "Physician",
        ("29-1215", "29-1062", "29-1063", "29-1069", "29-1228", "29-1216", "29-1218"),
        ("doctor", "medical-doctor", "internist"),
        "Physicians diagnose and treat illnesses and injuries across a wide range "
        "of medical specialties.",
    ),
    Occupation(
        "pharmacist", "Pharmacist",
        ("29-1051",),
        (),
        "Pharmacists dispense prescription medications and advise patients on safe "
        "and effective use.",
    ),
    # ---- Law & Academia ----
    Occupation(
        "attorney", "Attorney / Lawyer",
        ("23-1011",),
        ("lawyer", "associate-attorney"),
        "Lawyers advise and represent clients on legal matters, drawing the highest "
        "median salaries among sponsored occupations.",
    ),
    Occupation(
        "professor", "Postsecondary Professor / Instructor",
        ("25-1199", "25-1099", "25-1071", "25-1072"),
        ("assistant-professor", "lecturer", "postdoctoral-researcher", "professor-postsecondary"),
        "Postsecondary teachers instruct students and conduct research at colleges "
        "and universities.",
    ),
    # ---- Skilled & manual (PERM-heavy green-card sponsorship) ----
    Occupation(
        "truck-driver", "Heavy & Tractor-Trailer Truck Driver",
        ("53-3032",),
        ("trucker", "cdl-driver"),
        "Heavy and tractor-trailer truck drivers transport goods over intercity "
        "routes — a common PERM green-card occupation.",
    ),
    Occupation(
        "cook", "Cook",
        ("35-2014",),
        ("chef", "restaurant-cook"),
        "Cooks prepare and cook food in restaurants and other dining "
        "establishments — a frequent PERM sponsorship role.",
    ),
    Occupation(
        "nursing-assistant", "Nursing Assistant / Aide",
        ("31-1131", "31-1014"),
        ("nursing-aide", "cna", "patient-care-assistant"),
        "Nursing assistants provide basic care and help patients with daily "
        "activities under nurse supervision.",
    ),
    Occupation(
        "home-health-aide", "Home Health & Personal Care Aide",
        ("31-1121", "31-1011"),
        ("caregiver", "personal-care-aide", "home-health-aide"),
        "Home health and personal care aides assist elderly, disabled, or "
        "recovering people with daily living.",
    ),
)


_BY_SLUG: dict[str, Occupation] = {o.slug: o for o in OCCUPATIONS}
# alias slug -> canonical occupation (for 301 redirects to the canonical page)
_BY_ALIAS: dict[str, Occupation] = {
    alias: o for o in OCCUPATIONS for alias in o.aliases
}


def get_occupation(slug: str) -> Occupation | None:
    """Return the Occupation for a canonical slug, else None."""
    return _BY_SLUG.get(slug)


def resolve_alias(slug: str) -> Occupation | None:
    """Return the canonical Occupation an alias slug points to, else None."""
    return _BY_ALIAS.get(slug)


def all_occupations() -> tuple[Occupation, ...]:
    """All registered occupations, registry order."""
    return OCCUPATIONS


def normalize_to_slug(text: str) -> str:
    """Slugify free text the same way the registry slugs are formed.

    Lets a search term ("Software Engineer") be matched against canonical slugs
    and aliases.
    """
    return slugify(text)
