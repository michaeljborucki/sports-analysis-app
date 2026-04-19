"use client";
import { formatAmerican } from "@/lib/format";
import { BookLogo } from "../book-logo";

/**
 * The "Best odds" cell — the winning price + the book's branded pill beneath it.
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
