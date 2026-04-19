"use client";
import { useState } from "react";
import clsx from "clsx";
import { bookInfo } from "@/lib/books";

/**
 * Sportsbook brand — real logo pulled from Google's public favicon service at
 * 128px, falling back to a colored-letter pill if the image fails to load or
 * the book has no registered domain.
 *
 * Runtime-only (the image is fetched from google.com); if the user is offline
 * the pill fallback takes over. For a fully local build, these files could be
 * predownloaded into /public/logos/ — deferred to later.
 *
 *   mode="header" : monochrome in column headers
 *   mode="full"   : full color — for best-cell
 *   mode="label"  : small full color — for filter / inline labels
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
    const src = `https://www.google.com/s2/favicons?domain=${info.domain}&sz=128`;
    return (
      <span
        title={info.name}
        className={clsx(
          "inline-flex items-center justify-center rounded-sm overflow-hidden",
          mode === "header"
            ? "bg-bg-2/60 border border-border-subtle"
            : "bg-white",
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

  // Fallback: colored-letter pill
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
