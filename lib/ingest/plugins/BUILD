# BUILD file for ingest plugins

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "dol_lca",
    srcs = ["dol_lca.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//lib/ingest/plugins:salary_validation",
        "//models/ingest:data_source",
        "//models/ingest:ingest_run",
        "//models/ingest:enums",
        "//models:salary",
        "//models/enums:visa_program",
        "//lib/parsing/salary:db_importer",
        "//lib/parsing/salary:wage_unit_correction",
        "//lib/parsing/salary:file_detection",
        "//lib/business/salary:employer_clustering",
        "//lib/utils:http_utils",
        "//lib/utils:logging_utils",
        "//lib/utils:excel_utils",
        requirement("Django"),
    ],
)

py_library(
    name = "uscis_i129",
    srcs = ["uscis_i129.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//models/ingest:ingest_run",
        "//models/ingest:enums",
        "//models:i129",
        "//models/enums:visa_program",
        "//lib/utils:http_utils",
        requirement("Django"),
        requirement("requests"),
    ],
)

py_library(
    name = "dol_perm",
    srcs = ["dol_perm.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//lib/ingest/plugins:salary_validation",
        "//models/ingest:data_source",
        "//models/ingest:ingest_run",
        "//models/ingest:enums",
        "//models:salary",
        "//models/enums:visa_program",
        "//lib/parsing/salary:db_importer",
        "//lib/parsing/salary:wage_unit_correction",
        "//lib/business/salary:employer_clustering",
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        requirement("Django"),
    ],
)

py_library(
    name = "visa_bulletin",
    srcs = ["visa_bulletin.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//models/ingest:data_source",
        "//models/ingest:ingest_run",
        "//models/ingest:enums",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:table_to_cutoff_data",
        "//lib/parsing/bulletin:publication_data",
        "//lib/utils:http_utils",
        requirement("Django"),
    ],
)

py_library(
    name = "salary_validation",
    srcs = ["salary_validation.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//lib/utils:location_utils",
        "//models/ingest:ingest_run",
        "//models:salary",
        "//models/enums:visa_program",
        requirement("Django"),
    ],
)

py_library(
    name = "plugins",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":dol_lca",
        ":dol_perm",
        ":visa_bulletin",
        ":uscis",
        ":uscis_i129",
        ":uscis_datahub",
        ":dos",
        ":dol_perm_supply",
    ],
)

py_library(
    name = "uscis_datahub",
    srcs = ["uscis_datahub.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//models/ingest:enums",
        "//models/ingest:ingest_run",
        "//models:uscis_employer",
        requirement("Django"),
    ],
)

py_library(
    name = "uscis",
    srcs = ["uscis.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//models/ingest:enums",
        "//models/ingest:ingest_run",
        "//models:raw_facts",
        "//lib/business/vqs:ingest_utils",
        requirement("Django"),
    ],
)

py_library(
    name = "dos",
    srcs = ["dos.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//models/ingest:enums",
        "//models/ingest:ingest_run",
        "//models:raw_facts",
        "//lib/business/vqs:ingest_utils",
        "//lib/utils:http_utils",
        requirement("Django"),
        requirement("pdfplumber"),
    ],
)

py_library(
    name = "dol_perm_supply",
    srcs = ["dol_perm_supply.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:base",
        "//models/ingest:enums",
        "//models/ingest:ingest_run",
        "//models:raw_facts",
        "//lib/business/vqs:ingest_utils",
        "//lib/parsing/salary:db_importer",
        "//lib/utils:http_utils",
        requirement("Django"),
    ],
)
