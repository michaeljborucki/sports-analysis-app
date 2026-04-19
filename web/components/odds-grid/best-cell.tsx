"use client";
import { formatAmerican } from "@/lib/format";
import { BookLogo } from "../book-logo";

/**
 * The "Best odds" cell — price + branded book pill. Prices are already
 * commission-adjusted server-side, so no conversion happens here.
 */
export function BestCell({ price, book }: { price: number; book: string }) {
  return (
    <span className="inline-flex flex-col items-end gap-0.5 leading-none">
      <span className="text-price-up font-semibold tabular">
        {formatAmerican(price)}
      </span>
      <BookLogo bookKey={book} mode="label" />
    </span>
  );
}
