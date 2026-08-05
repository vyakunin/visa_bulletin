"""Guard: the gunicorn ``--preload`` master must compile no Django template.

Prod serves three monetization partials as ``:ro`` bind-mounts over
``webapp/templates/webapp/includes/{ad_slot,affiliate_card,support_cta}.html``.
With ``DEBUG=False`` + ``APP_DIRS=True`` and no explicit ``loaders``, Django wraps
its loader chain in ``cached.Loader``, which compiles a template once per process
and never re-stats the file — so an edited bind-mount stays invisible to any
worker that has already rendered it.

That cache lives in the WORKER, not the master, because nothing renders during
preload. So a graceful ``SIGHUP`` replaces every worker with a fresh fork whose
cache is empty, and the new partial is served immediately — no container
recreate, and no boot window in which nginx has nothing to connect to.

Measured 2026-08-05 on staging, against the real 36 KB ``affiliate_card.html``
mount: marker written to the mounted file was NOT served over 6 requests (the
cache holding it), then ``docker kill --signal=HUP`` served it 0.23s later, with
204 ok / 1 reset over 12s of continuous polling. The container recreate it
replaces costs a ~7.4s window in which the socket is unbound (1.1s drain + 0.9s
interpreter/Django import + 0.02s no-op migrate + 0.45s collectstatic + 4.5s
``--preload`` import incl. the VQS warmup), which is what turns into the 10-30
502s per override deploy recorded on the tracker ticket.

The mechanism holds ONLY while nothing compiles a template during preload. If
``AppConfig.ready()`` — or any import it triggers — rendered one, the master's
cache would be populated and inherited copy-on-write by every forked worker;
SIGHUP would silently stop picking up override edits, and the container recreate
would become the only way to ship a partial again. Nothing today does that
(``webapp.apps`` imports numpy and runs a VQS predict, neither of which touches
the template engine), and these tests pin it that way.
"""

import django
from django.template import engines
from django.template.engine import Engine
from django.template.loaders.cached import Loader as CachedLoader

# Run the preload path itself, at import, before anything renders: this is what
# `gunicorn --preload ... django_config.wsgi:application` does to the master —
# load settings and run every AppConfig.ready(). Idempotent if already populated.
django.setup()


def _cached_loaders(engine):
    """Every ``cached.Loader`` in an engine's loader chain, outermost first."""
    found = []
    pending = list(engine.template_loaders)
    while pending:
        loader = pending.pop(0)
        if isinstance(loader, CachedLoader):
            found.append(loader)
        pending.extend(getattr(loader, "loaders", []))
    return found


def test_prod_template_config_enables_cached_loader():
    """DEBUG=False + APP_DIRS + no explicit loaders => compiled templates are cached.

    This is *why* a bind-mounted override needs a worker-recycle signal at all.
    If a Django upgrade stopped auto-wrapping the chain, overrides would begin
    hot-reloading on their own and the SIGHUP step could be dropped — so this
    failing is a signal to revisit the override deploy, not merely a broken test.
    """
    engine = Engine(dirs=[], app_dirs=True, debug=False)
    assert _cached_loaders(engine), (
        "prod's template config no longer wraps loaders in cached.Loader; "
        "the override-deploy reload path assumes it does"
    )


def test_preload_master_compiles_no_templates():
    """Importing the app (what ``--preload`` does) must leave the cache empty.

    This test process is a faithful stand-in for the preload master: a fresh
    interpreter that has imported settings and run every ``AppConfig.ready()``,
    and rendered nothing. A non-empty cache here means some import-time or
    ``ready()`` code path compiled a template, which would poison every forked
    worker and break SIGHUP-based override deploys.
    """
    engine = engines["django"].engine
    cached = _cached_loaders(engine)
    assert cached, "expected cached.Loader under the app's DEBUG=False test config"
    for loader in cached:
        assert loader.get_template_cache == {}, (
            "a template was compiled during app import / AppConfig.ready(); the "
            "gunicorn --preload master would inherit this cache to every worker "
            "and SIGHUP would stop reloading the bind-mounted overrides: "
            f"{sorted(loader.get_template_cache)}"
        )
