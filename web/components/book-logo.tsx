"use client";
import { useState } from "react";
import clsx from "clsx";
import { bookInfo } from "@/lib/books";

// Mirror of /public/logos/*.png filenames (minus extension). Regenerate with
// `ls web/public/logos | sed 's/\.png$//'` when adding or removing logos.
// Used to avoid firing a <img src> for a file we know doesn't exist — the
// dev-tools 404s were cosmetically ugly and polluted the console sweep.
const LOGO_DOMAINS = new Set<string>([
  "1xbet.com", "888sport.com", "ballybet.com", "bet365.com", "betanysports.eu",
  "betmgm.com", "betonline.ag", "betparx.com", "betrivers.com", "betsson.com",
  "betus.com.pa", "betvictor.com", "betway.com", "bovada.lv", "boylesports.com",
  "caesars.com", "casumo.com", "coolbet.com", "coral.co.uk", "draftkings.com",
  "espnbet.com", "everygame.eu", "fanatics.com", "fanduel.com", "grosvenorsport.com",
  "hardrockbet.com", "ladbrokes.com", "leovegas.com", "livescorebet.com",
  "marathonbet.com", "matchbook.com", "mybookie.ag", "nordicbet.com", "novig.us",
  "paddypower.com", "pinnacle.com", "pmu.fr", "pointsbet.com", "prophetx.co",
  "rebet.app", "smarkets.com", "sporttrade.com", "tipico.de", "unibet.fr",
  "unibet.nl", "unibet.se", "virginbet.com", "williamhill.com", "winamax.de",
  "winamax.fr",
]);

/**
 * Sportsbook brand logo — references a locally-bundled, auto-trimmed PNG under
 * /public/logos/<domain>.png (regenerate via scripts/download_logos.py). Falls
 * back to a colored-letter pill if the logo is missing or fails to load.
 *
 *   mode="header" : monochrome for column headers
 *   mode="full"   : full color — Best cell
 *   mode="label"  : small full color — filter / inline
 */
export function BookLogo({
  bookKey,
  mode = "header",
  className,
}: {
  bookKey: string;
  mode?: "header" | "full" | "label";
  className?: string;
}) {
  const info = bookInfo(bookKey);
  const [imgFailed, setImgFailed] = useState(false);
  const hasLogo =
    !!info.domain && LOGO_DOMAINS.has(info.domain) && !imgFailed;

  const size =
    mode === "label"
      ? { h: 16, w: 28, textSize: "text-[9px]" }
      : { h: 20, w: 36, textSize: "text-[10px]" };

  // Full color in every mode — the user wants brand-recognizable headers.
  // The old monochrome-on-header treatment (from competitor research) is
  // available if we ever re-introduce it.
  const filter: string | undefined = undefined;

  if (hasLogo) {
    const src = `/logos/${info.domain}.png`;
    return (
      <span
        title={info.name}
        className={clsx(
          "inline-flex items-center justify-center rounded-sm overflow-hidden",
          className
        )}
        style={{ height: size.h, width: size.w }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={info.name}
          loading="lazy"
          decoding="async"
          onError={() => setImgFailed(true)}
          style={{
            maxWidth: "100%",
            maxHeight: "100%",
            objectFit: "contain",
            filter,
          }}
        />
      </span>
    );
  }

  // Fallback: colored-letter pill (only for books with no local logo file)
  if (mode === "header") {
    return (
      <span
        title={info.name}
        className={clsx(
          "inline-flex items-center justify-center px-1.5 rounded-sm",
          "font-bold tracking-wide uppercase",
          "bg-bg-2 text-text-2 border border-border-subtle",
          size.textSize,
          className
        )}
        style={{ height: size.h, minWidth: size.w }}
      >
        {info.label}
      </span>
    );
  }

  return (
    <span
      title={info.name}
      className={clsx(
        "inline-flex items-center justify-center px-1.5 rounded-sm",
        "font-bold tracking-wide uppercase",
        size.textSize,
        className
      )}
      style={{
        height: size.h,
        minWidth: size.w,
        background: info.bg,
        color: info.fg,
      }}
    >
      {info.label}
    </span>
  );
}
