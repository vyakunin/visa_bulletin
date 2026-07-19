load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# Library form so //tests:test_render_sitemap can import the safety gates
# (check_safety_gates / write_atomically) without depending on an executable.
py_library(
    name = "render_sitemap_lib",
    srcs = ["render_sitemap.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//webapp/views/seo:sitemaps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("redis"),  # Django Redis cache backend; the qualifying_* helpers read it
    ],
)

py_binary(
    name = "render_sitemap",
    srcs = ["render_sitemap.py"],
    main = "render_sitemap.py",
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    visibility = ["//visibility:public"],
    deps = [":render_sitemap_lib"],
)
