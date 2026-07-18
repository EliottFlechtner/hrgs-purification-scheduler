"""Tests for hrgs_scheduler.models.network_config (HopConfig, NetworkConfig)."""

import pytest

from hrgs_scheduler.models.network_config import HopConfig, NetworkConfig


def test_hop_config_eta_computed_from_attenuation():
    hop = HopConfig(
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        attenuation_db_per_km=0.2,
    )
    expected_eta = 10.0 ** (-0.2 * 2.0 / 10.0)
    assert hop.eta == pytest.approx(expected_eta)


def test_hop_config_explicit_eta_overrides_attenuation():
    hop = HopConfig(
        length=2.0,
        branching=(1,),
        arm_count=1,
        p_x_inner=0.0,
        p_z_inner=0.0,
        eta=0.5,
    )
    assert hop.eta == 0.5


def test_hop_config_rejects_invalid_eta():
    with pytest.raises(ValueError):
        HopConfig(
            length=1.0,
            branching=(1,),
            arm_count=1,
            p_x_inner=0.0,
            p_z_inner=0.0,
            eta=1.5,
        )


def test_hop_config_rejects_empty_branching():
    with pytest.raises(ValueError):
        HopConfig(
            length=1.0,
            branching=(),
            arm_count=1,
            p_x_inner=0.0,
            p_z_inner=0.0,
            eta=0.5,
        )


def test_tree_depth_is_branching_length():
    hop = HopConfig(
        length=1.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        eta=0.5,
    )
    assert hop.tree_depth == 3


def test_inner_error_per_hop_uses_arm_count_not_tree_depth():
    # Regression test: eq. (10)'s (m-1) exponent must use arm_count,
    # NOT tree_depth (branching vector length) -- see docstring/repo notes.
    hop = HopConfig(
        length=1.0,
        branching=(16, 14, 1),  # tree_depth = 3
        arm_count=18,  # arm_count = 18, must be used as 'm'
        p_x_inner=0.01,
        p_z_inner=0.02,
        eta=0.5,
    )
    m = hop.arm_count
    expected = 0.5 * (1.0 - (1.0 - 2.0 * 0.01) * (1.0 - 2.0 * 0.02) ** (m - 1))
    assert hop.inner_error_per_hop == pytest.approx(expected)
    # sanity: using tree_depth instead would give a different (wrong) value
    wrong_m = hop.tree_depth
    wrong = 0.5 * (1.0 - (1.0 - 2.0 * 0.01) * (1.0 - 2.0 * 0.02) ** (wrong_m - 1))
    assert hop.inner_error_per_hop != pytest.approx(wrong)


def test_inner_error_per_hop_zero_when_ideal():
    hop = HopConfig(
        length=1.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        eta=0.5,
    )
    assert hop.inner_error_per_hop == pytest.approx(0.0)


def test_bsm_success_prob_capped_at_half():
    hop = HopConfig(
        length=1.0,
        branching=(1,),
        arm_count=1,
        p_x_inner=0.0,
        p_z_inner=0.0,
        eta=1.0,
    )
    assert hop.bsm_success_prob_per_arm == pytest.approx(0.5)


def test_bsm_success_prob_scales_with_eta_below_cap():
    hop = HopConfig(
        length=1.0,
        branching=(1,),
        arm_count=1,
        p_x_inner=0.0,
        p_z_inner=0.0,
        eta=0.4,
    )
    assert hop.bsm_success_prob_per_arm == pytest.approx(0.2)


def test_network_config_rejects_empty_hops():
    with pytest.raises(ValueError):
        NetworkConfig(hops=(), e_d=0.0, gamma=0.0, c=2e5)


def test_network_config_n_and_total_length():
    net = NetworkConfig.uniform(
        N=10,
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        e_d=0.0,
    )
    assert net.N == 10
    assert net.total_length() == pytest.approx(20.0)


def test_network_config_hop_accessor():
    net = NetworkConfig.uniform(
        N=3,
        length=1.5,
        branching=(2,),
        arm_count=4,
        p_x_inner=0.0,
        p_z_inner=0.0,
    )
    assert net.hop(0).length == 1.5
    assert net.hop(2).length == 1.5


def test_integrating_paper_config_matches_section_v_a():
    net = NetworkConfig.integrating_paper_config(e_d=0.005)
    assert net.N == 10
    assert net.total_length() == pytest.approx(20.0)
    assert net.e_d == 0.005
    assert net.gamma == 0.0
    assert net.c == pytest.approx(2e5)
    hop0 = net.hop(0)
    assert hop0.length == pytest.approx(2.0)
    assert hop0.branching == (16, 14, 1)
    assert hop0.arm_count == 18


def test_inner_error_e2e_zero_for_ideal_inner_qubits():
    net = NetworkConfig.integrating_paper_config(e_d=0.0)
    p_zi, p_iz = net.inner_error_e2e()
    assert p_zi == pytest.approx(0.0)
    assert p_iz == pytest.approx(0.0)
