from scrapers.news import FightContext, build_fight_context


def test_fight_context_defaults():
    ctx = FightContext(fighter_name="Islam Makhachev")
    assert ctx.fighter_name == "Islam Makhachev"
    assert ctx.injuries == []
    assert ctx.camp_info == ""
    assert ctx.weight_cut_notes == ""
    assert ctx.layoff_days is None
    assert ctx.short_notice is False


def test_build_fight_context_returns_context():
    ctx = build_fight_context("Unknown Fighter")
    assert isinstance(ctx, FightContext)
    assert ctx.fighter_name == "Unknown Fighter"
