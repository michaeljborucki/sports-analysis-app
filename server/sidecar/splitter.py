"""Plan how a Kelly target gets allocated across the account pool.

Multi-parlay-per-account walk; lowest balance first; stack max-cap parlays
on each account until it can't fund another; take one partial; peel-back
when the residual would drop below the per-parlay floor."""
from __future__ import annotations

from server.sidecar.models import (
    AccountSnapshot,
    SplitAssignment,
    SplitPlan,
)


FLOOR = 30   # dollars; no individual parlay smaller than this


def plan_splits(
    target: int,
    accounts: list[AccountSnapshot],
    pinned_customer_id: str | None = None,
) -> SplitPlan:
    """Plan a placement.

    ``pinned_customer_id`` (account-first /sidecar flow) constrains the
    candidate pool to that one account. Within that constraint the same
    multi-parlay-per-account stacking logic runs: pack full-cap parlays
    until balance runs out, take one partial, peel back if the residual
    would drop below the floor. Cross-account peel-back is suppressed —
    a pinned plan never spills into a second account.
    """
    if target < FLOOR:
        return SplitPlan(assignments=[], status="below_minimum", target=target)

    if pinned_customer_id is not None:
        accounts = [a for a in accounts if a.customer_id == pinned_customer_id]
    eligible = sorted(
        [a for a in accounts if a.available_balance >= FLOOR],
        key=lambda a: a.available_balance,
    )
    if not eligible:
        return SplitPlan(
            assignments=[], status="no_eligible_account", target=target,
        )

    assignments: list[SplitAssignment] = []
    remaining = target
    # Track remaining per-account balance so peel-back can avoid drained
    # accounts even though AccountSnapshot.available_balance is immutable.
    running: dict[str, int] = {
        a.customer_id: int(a.available_balance) for a in eligible
    }

    for account in eligible:
        if remaining == 0:
            break
        balance = running[account.customer_id]
        cap = account.max_parlay_stake

        # Pack full-cap parlays on this account
        while balance >= cap and remaining >= cap:
            assignments.append(SplitAssignment(account, cap))
            balance -= cap
            remaining -= cap

        if remaining == 0:
            running[account.customer_id] = balance
            break

        # Try one partial parlay on this account
        partial = min(balance, remaining, cap)
        if partial < FLOOR:
            running[account.customer_id] = balance
            continue
        new_remaining = remaining - partial
        if new_remaining == 0 or new_remaining >= FLOOR:
            assignments.append(SplitAssignment(account, partial))
            balance -= partial
            remaining = new_remaining
        else:
            # Shrink this partial so residual lands on FLOOR exactly
            adjusted = partial - (FLOOR - new_remaining)
            if adjusted >= FLOOR:
                assignments.append(SplitAssignment(account, adjusted))
                balance -= adjusted
                remaining = FLOOR
        running[account.customer_id] = balance

    # Final peel-back: reduce last assignment by (FLOOR - remaining) and
    # place a fresh FLOOR-sized bet on the next-cheapest non-same account
    # that still has FLOOR of remaining (not just original) balance.
    # Pinned plans cannot peel back to another account — by construction
    # there isn't one.
    if pinned_customer_id is None and 0 < remaining < FLOOR and assignments:
        last = assignments[-1]
        deficit = FLOOR - remaining
        if last.amount - deficit >= FLOOR:
            alt = next(
                (a for a in eligible
                 if a.customer_id != last.account.customer_id
                 and running.get(a.customer_id, 0) >= FLOOR),
                None,
            )
            if alt is not None:
                last.amount -= deficit
                assignments.append(SplitAssignment(alt, FLOOR))
                remaining = 0

    status = "planned" if remaining == 0 else "partial_fill"
    return SplitPlan(assignments=assignments, status=status, target=target)
