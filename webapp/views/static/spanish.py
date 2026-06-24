"""Spanish-language (/es/) cluster pages.

Static Spanish siblings that convert real Spanish search demand ("boletín de
visas", "fecha de prioridad eb2 india", "predicciones boletín de visas") without
the cost of full Django i18n. Each page links into the live English data widgets
(dashboard, salaries, prediction archive) — the interface is visual (dates,
categories, countries) and navigable without advanced English. The Spanish landing
explainer lives in ``pages.py``; the per-EB-class x per-country priority-date
landing siblings live in ``webapp/views/bulletin/priority_date_landing.py``.
"""

import json

from django.shortcuts import render

from webapp.views.bulletin.priority_date_landing import (
    _COUNTRIES,
    _EB_CLASSES,
    _ES_COUNTRY,
)


def _faqpage_schema(faq: list[dict]) -> str:
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
                }
                for item in faq
            ],
        }
    )


# 8 Spanish FAQs mirroring the English /faq/ set (kept self-contained so the
# Spanish page stands alone for the "preguntas frecuentes boletín de visas" query).
_ES_FAQ = [
    {
        "q": "¿Este panel rastrea los tiempos de procesamiento de PERM?",
        "a": (
            "No. Este panel rastrea únicamente el movimiento de las fechas de corte del "
            "Boletín de Visas, no los tiempos de procesamiento de PERM. El procesamiento "
            "de PERM es cuánto tarda el Departamento de Trabajo (DOL) en aprobar tu "
            "certificación laboral. La espera del Boletín de Visas (lo que sí rastrea este "
            "panel) empieza cuando tu PERM ya está aprobada: tu fecha de presentación de "
            "PERM se convierte en tu fecha de prioridad, y el Boletín de Visas publica "
            "cortes mensuales que muestran cómo se han movido y proyecta cuándo tu fecha "
            "podría volverse actual."
        ),
    },
    {
        "q": "¿Cuál es la diferencia entre \"Acción Final\" y \"Fechas de Presentación\"?",
        "a": (
            "Fechas de Acción Final: cuando tu fecha de prioridad alcanza este corte, USCIS "
            "puede aprobar tu green card (I-485). Fechas de Presentación: cuando tu fecha de "
            "prioridad alcanza este corte, puedes presentar tu solicitud I-485 (Ajuste de "
            "Estatus), pero no se aprobará hasta que la fecha de Acción Final también sea "
            "actual. La mayoría de la gente observa las Fechas de Acción Final, porque "
            "determinan cuándo realmente obtienes la green card."
        ),
    },
    {
        "q": "¿Qué es una fecha de prioridad?",
        "a": (
            "Tu fecha de prioridad es la fecha en que se presentó tu petición de inmigración. "
            "En casos familiares es la fecha en que tu patrocinador presentó la petición I-130. "
            "En casos basados en empleo es la fecha en que se presentó tu certificación laboral "
            "PERM (o la I-140 si estás exento de PERM). El Boletín de Visas publica cortes "
            "mensuales. Si tu fecha de prioridad es anterior al corte, tu caso puede avanzar."
        ),
    },
    {
        "q": "¿Cómo funciona el modelo Bulletin Forecast y qué tan preciso es?",
        "a": (
            "El modelo Bulletin Forecast funciona en dos etapas. Para la predicción del próximo "
            "mes, clasifica el régimen actual de cada serie (avanzando, estancada o "
            "retrocediendo) y aplica la estrategia más precisa para ese estado — por defecto "
            "predice sin cambios cuando está estancada y aplica patrones estacionales históricos "
            "cuando avanza activamente. Para horizontes de 6 a 12 meses toma el control un "
            "modelo de machine learning (gradient boosting) entrenado con más de una década de "
            "historial del boletín, datos de demanda I-140 y ciclos del año fiscal. En "
            "horizontes de 6 meses para las series clave de India/China EB-2/EB-3 logra errores "
            "absolutos medios de 155 a 264 días, mejor que simplemente asumir que no habrá "
            "cambios (~280 días)."
        ),
    },
    {
        "q": "¿Por qué a veces las fechas de prioridad retroceden (retrogresión)?",
        "a": (
            "La retrogresión ocurre cuando la demanda de visas supera la cuota anual. El "
            "Departamento de Estado mueve los cortes hacia atrás para frenar la emisión de "
            "visas. Causas comunes incluyen un aumento de solicitudes nuevas, cambios de "
            "política de USCIS que aceleran aprobaciones y ajustes de fin de año fiscal."
        ),
    },
    {
        "q": "¿Dónde están los padres/cónyuges de ciudadanos de EE.UU. (Familiares Inmediatos)?",
        "a": (
            "Los padres, cónyuges e hijos solteros menores de 21 años de ciudadanos "
            "estadounidenses son Familiares Inmediatos (IR) y no están sujetos a las cuotas del "
            "Boletín de Visas. No aparecen en este panel porque no hay cortes mensuales que "
            "rastrear — las visas están disponibles de inmediato una vez que USCIS aprueba la "
            "petición. Este panel solo rastrea las categorías de Preferencia Familiar (F1, F2A, "
            "F2B, F3, F4) y las categorías basadas en empleo (EB1-EB5), que tienen cuotas anuales."
        ),
    },
    {
        "q": "¿Con qué frecuencia se actualizan los datos?",
        "a": (
            "El panel se actualiza automáticamente todos los días para comprobar si hay un "
            "nuevo Boletín de Visas del Departamento de Estado. El boletín oficial suele "
            "publicarse a mediados de cada mes para el mes siguiente. Todos los datos provienen "
            "directamente de travel.state.gov."
        ),
    },
    {
        "q": "¿Esta herramienta es de código abierto?",
        "a": (
            "Sí. Todo el código está disponible en GitHub en "
            "https://github.com/vyakunin/visa_bulletin. Puedes ver el código fuente, reportar "
            "errores o pedir funciones, contribuir mejoras y ejecutar tu propia instancia local."
        ),
    },
]


def spanish_faq_view(request):
    """Spanish FAQ page (/es/faq/) with FAQPage JSON-LD."""
    return render(
        request,
        "webapp/spanish_faq.html",
        {
            "page_title": "Preguntas Frecuentes — Boletín de Visas (español)",
            "page_description": (
                "Preguntas frecuentes en español sobre fechas de prioridad, PERM, Acción Final "
                "vs Fechas de Presentación, retrogresión y cómo funciona el Boletín de Visas."
            ),
            "canonical_url": request.build_absolute_uri("/es/faq/"),
            "hreflang_es": request.build_absolute_uri("/es/faq/"),
            "hreflang_en": request.build_absolute_uri("/faq/"),
            "faq": _ES_FAQ,
            "structured_data": _faqpage_schema(_ES_FAQ),
        },
    )


def spanish_predictions_view(request):
    """Spanish explainer for the prediction model (/es/predictions/).

    The live prediction archive + tables stay English (data widgets); this page
    explains the model in Spanish and links into them, capturing the
    "predicciones boletín de visas" demand.
    """
    return render(
        request,
        "webapp/spanish_predictions.html",
        {
            "page_title": "Predicciones del Boletín de Visas — Cómo Funciona el Modelo",
            "page_description": (
                "Predicciones mensuales de fechas de prioridad del Boletín de Visas con el "
                "modelo Bulletin Forecast: cómo funciona, qué tan preciso es y dónde ver el "
                "archivo de precisión histórica."
            ),
            "canonical_url": request.build_absolute_uri("/es/predictions/"),
            "hreflang_es": request.build_absolute_uri("/es/predictions/"),
            "hreflang_en": request.build_absolute_uri("/predictions/"),
        },
    )


def spanish_priority_date_hub_view(request):
    """Spanish priority-date hub (/es/priority-date/) — index of the 12 ES pages."""
    groups = []
    for eb_slug, (eb_short, _full) in _EB_CLASSES.items():
        groups.append(
            {
                "eb_short": eb_short,
                "countries": [
                    {"label": _ES_COUNTRY[c_slug], "url": f"/es/priority-date/{eb_slug}/{c_slug}/"}
                    for c_slug in _COUNTRIES
                ],
            }
        )
    return render(
        request,
        "webapp/spanish_priority_date_hub.html",
        {
            "page_title": "Fechas de Prioridad por Categoría y País — Boletín de Visas",
            "page_description": (
                "Fechas de prioridad actuales del Boletín de Visas de EE.UU. por categoría "
                "(EB-1, EB-2, EB-3) y país (India, China, Filipinas, México), con tendencia "
                "mensual e historial."
            ),
            "canonical_url": request.build_absolute_uri("/es/priority-date/"),
            "hreflang_es": request.build_absolute_uri("/es/priority-date/"),
            "hreflang_en": request.build_absolute_uri("/priority-date/"),
            "groups": groups,
        },
    )
