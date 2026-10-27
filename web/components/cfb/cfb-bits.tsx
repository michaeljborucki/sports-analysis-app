"use client";

export function TeamLogo({
  side,
  size = 20,
}: {
  side: { logo: string | null; name: string };
  size?: number;
}) {
  const style = { width: size, height: size };
  if (!side.logo) return <span className="inline-block shrink-0" style={style} />;
  // Plain <img>: ESPN's CDN isn't an allowed next/image host, and these are tiny.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={side.logo} alt="" style={style} className="shrink-0 object-contain" loading="lazy" />;
}

export function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="search"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder="Filter teams"
      aria-label="Filter teams"
      className="h-7 w-44 rounded border border-border-subtle bg-bg-0 px-2 text-[length:var(--fs-13)] text-text-1 placeholder:text-text-3"
    />
  );
}
