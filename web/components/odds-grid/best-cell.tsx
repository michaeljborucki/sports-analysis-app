"use client";
import { formatAmerican } from "@/lib/format";
import { effectiveForBook } from "@/lib/effective-odds";
import { bookInfo } from "@/lib/books";
import { BookLogo } from "../book-logo";

/**
 * The "Best odds" cell. `price` is the book's **listed** American odds; if the
 * book charges commission, we display the commission-adjusted effective price
 * as the headline (that's the apples-to-apples number for comparison across
 * books) with a small "(listed: X)" subscript so the user can still see the
 * raw quote.
 */
export function BestCell({ price, book }: { price: number; book: string }) {
  const info = bookInfo(book);
  const effective = effectiveForBook(price, book);
  const hasCommission = (info.commission ?? 0) > 0 && effective !== price;

  return (
    <span className="inline-flex flex-col items-end gap-0.5 leading-none">
      <span className="text-price-up font-semibold tabular">
        {formatAmerican(effective)}
        {hasCommission && (
          <span
            className="ml-0.5 text-text-3 text-[9px] font-normal"
            title={`Listed ${formatAmerican(price)} — ${(
              (info.commission ?? 0) * 100
            ).toFixed(0)}% commission`}
          >
            *
          </span>
        )}
      </span>
      <BookLogo bookKey={book} mode="label" />
    </span>
  );
}
