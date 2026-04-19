"use client";
import { useState } from "react";
import clsx from "clsx";
import { bookInfo } from "@/lib/books";

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
  const hasLogo = !!info.domain && !imgFailed;

  const size =
    mode === "label"
      ? { h: 16, w: 28, textSize: "text-[9px]" }
      : { h: 20, w: 36, textSize: "text-[10px]" };

  const filter =
    mode === "header"
      ? "grayscale(1) brightness(1.1) contrast(0.9) opacity(0.85)"
      : undefined;

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
