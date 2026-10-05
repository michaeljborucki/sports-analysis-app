"use client";

import type { Game } from "@/lib/api";
import type { Sport, MarketGroup } from "@/lib/sports";
import { renderTeam } from "@/lib/sports";
import { Chip } from "@/components/ui";
import { SideSheet } from "../side-sheet";
import { sentenceCaseLabel } from "./grid-style";
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
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="truncate text-[length:var(--fs-16)] leading-[var(--lh-16)] font-semibold text-text-1">
              {renderTeam(game.away_team, sport)}{" "}
              <span className="font-normal text-text-3">@</span>{" "}
              {renderTeam(game.home_team, sport)}
            </h2>
            <div className="flex items-center gap-2">
              <Chip>{sentenceCaseLabel(group.label)}</Chip>
              <span className="text-[length:var(--fs-12)] text-text-3">
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
