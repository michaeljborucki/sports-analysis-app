"use client";

import type { Game } from "@/lib/api";
import type { Sport, MarketGroup } from "@/lib/sports";
import { renderTeam } from "@/lib/sports";
import { SideSheet } from "../side-sheet";
import { MarketExpansionPanel } from "./market-expansion-panel";

/**
 * Right-docked side sheet showing alt-lines for a single game. Composes the
 * reusable `<SideSheet>` primitive with the per-game `<MarketExpansionPanel>`
 * body.
 *
 * Content is re-keyed by event_id so SWRMutation state inside the panel
 * resets cleanly when the user swaps games without closing the sheet.
 */
export function AltLinesSideSheet({
  game,
  sport,
  group,
  visible,
  open,
  onClose,
}: {
  /** Null while no game selected (sheet is closed). */
  game: Game | null;
  sport: Sport;
  group: MarketGroup;
  visible: Set<string>;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <SideSheet
      open={open && game != null}
      onClose={onClose}
      ariaLabel={
        game ? `${game.away_team} at ${game.home_team} alt lines` : "Alt lines"
      }
      header={
        game ? (
          <div className="flex flex-col gap-1 min-w-0">
            <div className="text-text-1 font-semibold text-sm truncate">
              {renderTeam(game.away_team, sport)}{" "}
              <span className="text-text-3 font-normal">@</span>{" "}
              {renderTeam(game.home_team, sport)}
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center px-1.5 h-4 rounded-sm text-[9px] font-semibold uppercase tracking-wider bg-accent/15 text-accent">
                {group.label}
              </span>
              <span className="text-[11px] text-text-3">
                Alt lines across books
              </span>
            </div>
          </div>
        ) : null
      }
    >
      {game && (
        <MarketExpansionPanel
          key={`${game.event_id}-${group.mainKey}`}
          game={game}
          sport={sport}
          group={group}
          visible={visible}
        />
      )}
    </SideSheet>
  );
}
