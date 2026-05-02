import pytest
from gpa.eval.migrate_layout import ParsedName, parse_existing_folder_name


def test_parse_synthetic():
    p = parse_existing_folder_name("e1_state_leak")
    assert p == ParsedName(round="e1", category_hint=None, framework_hint=None,
                           bug_class_hint=None, suffix="state_leak", kind="synthetic")


def test_parse_synthetic_long():
    p = parse_existing_folder_name("e25_gldepthrange_set_to_1_0_but_depth_test_is_gl_less_nothing_vi")
    assert p.kind == "synthetic"
    assert p.round == "e25"
    assert p.suffix == "gldepthrange_set_to_1_0_but_depth_test_is_gl_less_nothing_vi"


def test_parse_early_mined():
    p = parse_existing_folder_name("r14_bevy_child_text_invisible")
    assert p == ParsedName(round="r14", category_hint=None, framework_hint=None,
                           bug_class_hint=None, suffix="bevy_child_text_invisible",
                           kind="early-mined")


def test_parse_recent_mined_with_bug_class_and_taxonomy():
    p = parse_existing_folder_name(
        "r96fdc7_framework-maintenance_native-engine_godot_4_2_world_environment_glow_eff"
    )
    assert p.round == "r96fdc7"
    assert p.bug_class_hint == "framework-maintenance"
    assert p.category_hint == "native-engine"
    assert p.framework_hint == "godot"
    assert p.suffix == "4_2_world_environment_glow_eff"
    assert p.kind == "recent-mined"


def test_parse_recent_mined_web_map():
    p = parse_existing_folder_name(
        "rc2487a_framework-maintenance_web-map_mapbox-gl-js_symbol_icon_color_is_not_worki"
    )
    assert p.framework_hint == "mapbox-gl-js"
    assert p.category_hint == "web-map"


def test_parse_unknown_falls_back_to_legacy():
    p = parse_existing_folder_name("something_bizarre_with_no_prefix")
    assert p.kind == "unknown"


def test_parse_r9_is_early_mined_not_recent():
    # r9_<x> shouldn't match the recent-mined hex regex (which requires {6,8} hex chars).
    p = parse_existing_folder_name("r9_blend_modes_not_working")
    assert p.kind == "early-mined"
    assert p.round == "r9"
