"use client";
import { formatAmerican, formatBookAbbrev } from "@/lib/format";

export function BestCell({ price, book }: { price: number; book: string }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-price-up font-semibold tabular">
        {formatAmerican(price)}
      </span>
      <span className="text-text-3 text-[10px] uppercase tracking-wide">
        {formatBookAbbrev(book)}
      </span>
    </span>
  );
}
