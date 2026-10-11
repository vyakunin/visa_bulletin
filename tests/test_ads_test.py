"""Arm assignment for the ads-off split test (webapp/views/ads_test.py)."""

from webapp.views.ads_test import AdsArm, employer_ads_arm


def test_known_slugs_keep_their_arm():
    # A change to the salt or the hash moves pages between arms mid-test; these pin it.
    assert employer_ads_arm("acme-a") is AdsArm.ON
    assert employer_ads_arm("acme-b") is AdsArm.OFF
    assert employer_ads_arm("microsoft-corporation") is employer_ads_arm("microsoft-corporation")


def test_arms_split_the_surface_roughly_in_half():
    slugs = [f"employer-{i}" for i in range(20_000)]
    off = sum(employer_ads_arm(s) is AdsArm.OFF for s in slugs)
    assert 0.48 < off / len(slugs) < 0.52


def test_content_group_names_the_arm():
    assert AdsArm.OFF.content_group == "ads-test:off"
    assert AdsArm.ON.content_group == "ads-test:on"
