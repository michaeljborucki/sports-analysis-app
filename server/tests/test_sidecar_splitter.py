from server.odds.books.coral33.accounts import AccountCredential
from server.sidecar.models import AccountSnapshot
from server.sidecar.splitter import plan_splits, FLOOR


def _acct(cust, bal, cap=100):
    return AccountSnapshot(
        credential=AccountCredential(customer_id=cust, password="p",
                                     max_parlay_stake=cap),
        available_balance=bal,
    )


# --- worked examples from the spec ---

def test_target_300_a_balance_250_drains_then_moves_to_b():
    pool = [_acct("A", 250), _acct("B", 1000)]
    plan = plan_splits(300, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("A", 100), ("A", 100), ("A", 50), ("B", 50)]


def test_target_300_a_balance_500_all_on_a():
    pool = [_acct("A", 500), _acct("B", 1000)]
    plan = plan_splits(300, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("A", 100), ("A", 100), ("A", 100)]


def test_target_105_peelback_to_b():
    pool = [_acct("A", 1000), _acct("B", 1000)]
    plan = plan_splits(105, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("A", 75), ("B", 30)]


def test_target_260_a_balance_250():
    pool = [_acct("A", 250), _acct("B", 1000)]
    plan = plan_splits(260, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("A", 100), ("A", 100), ("A", 30), ("B", 30)]


def test_target_130_stanley_lowest_balance_takes_alone():
    stanley = _acct("STANLEY", 300, cap=150)
    other = _acct("B", 1000)
    pool = [stanley, other]
    plan = plan_splits(130, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("STANLEY", 130)]


def test_target_230_stacks_on_stanley():
    """Stanley's $300 balance covers a second parlay (Stanley cap=$150);
    the partial-step takes the $80 residual on Stanley before moving on
    to B. Consistent with the broader "drain balance before moving on"
    principle."""
    stanley = _acct("STANLEY", 300, cap=150)
    other = _acct("B", 1000)
    plan = plan_splits(230, [stanley, other])
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("STANLEY", 150), ("STANLEY", 80)]


# --- refusals ---

def test_below_minimum():
    plan = plan_splits(18, [_acct("A", 1000)])
    assert plan.status == "below_minimum"
    assert plan.assignments == []


def test_no_eligible_account():
    pool = [_acct("A", 20), _acct("B", 25)]   # neither has FLOOR
    plan = plan_splits(50, pool)
    assert plan.status == "no_eligible_account"


def test_partial_fill():
    # Only one acct has 80, request 200
    plan = plan_splits(200, [_acct("ONLY", 80)])
    assert plan.status == "partial_fill"
    assert plan.filled == 80
    assert plan.unfilled == 120


from hypothesis import given, strategies as st


@given(
    target=st.integers(min_value=0, max_value=2000),
    balances=st.lists(
        st.integers(min_value=0, max_value=2000),
        min_size=1, max_size=10,
    ),
    caps=st.lists(
        st.sampled_from([100, 150]),
        min_size=1, max_size=10,
    ),
)
def test_invariants_hold_for_arbitrary_inputs(target, balances, caps):
    pool = [
        _acct(f"A{i}", b, c)
        for i, (b, c) in enumerate(zip(balances, caps))
    ]
    plan = plan_splits(target, pool)

    if plan.status == "planned":
        assert plan.filled == target

    # Property 2: every amount ≥ FLOOR
    assert all(a.amount >= FLOOR for a in plan.assignments)

    # Property 3: per-parlay cap honored
    assert all(
        a.amount <= a.account.max_parlay_stake
        for a in plan.assignments
    )

    # Property 4: per-account total ≤ balance
    by_acct: dict[str, int] = {}
    for a in plan.assignments:
        by_acct.setdefault(a.account.customer_id, 0)
        by_acct[a.account.customer_id] += a.amount
    for cust, total in by_acct.items():
        bal = next(b for b, acc in zip(balances, pool)
                   if acc.customer_id == cust)
        assert total <= bal


# --- Pinned customer_id (account-first /sidecar flow) ---

def test_pinned_constrains_pool_to_one_account():
    """Pinning B forces the plan onto B even though A has the lowest
    balance (which the legacy splitter would prefer)."""
    pool = [_acct("A", 250), _acct("B", 1000)]
    plan = plan_splits(200, pool, pinned_customer_id="B")
    assert plan.status == "planned"
    used = {a.account.customer_id for a in plan.assignments}
    assert used == {"B"}
    assert sum(a.amount for a in plan.assignments) == 200


def test_pinned_stacks_multi_parlay_at_cap():
    """Target $300, pinned account cap $100 → three $100 parlays on it."""
    pool = [_acct("A", 100), _acct("B", 500)]
    plan = plan_splits(300, pool, pinned_customer_id="B")
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("B", 100), ("B", 100), ("B", 100)]


def test_pinned_below_floor_returns_no_eligible_account():
    """Pinned account has $20 (< $30 floor): no eligible accounts."""
    pool = [_acct("A", 20), _acct("B", 1000)]
    plan = plan_splits(100, pool, pinned_customer_id="A")
    assert plan.status == "no_eligible_account"
    assert plan.assignments == []


def test_pinned_partial_fill_does_not_peel_to_other_account():
    """Target $130 on a pinned $100 account: partial $100 + no peel-back
    to the second account. Legacy splitter would peel back; pinned must
    not."""
    pool = [_acct("A", 100, cap=100), _acct("B", 1000)]
    plan = plan_splits(130, pool, pinned_customer_id="A")
    used = {a.account.customer_id for a in plan.assignments}
    assert used == {"A"}
    assert plan.status == "partial_fill"
    assert sum(a.amount for a in plan.assignments) == 100
    assert plan.unfilled == 30


def test_pinned_unknown_customer_id_returns_no_eligible_account():
    """Pinning a customer_id that's not in the pool resolves to empty."""
    pool = [_acct("A", 500), _acct("B", 500)]
    plan = plan_splits(100, pool, pinned_customer_id="MISSING")
    assert plan.status == "no_eligible_account"
    assert plan.assignments == []
