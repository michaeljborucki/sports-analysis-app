import clsx from "clsx";

/** Surface container. Optional title row with right-side actions. */
export function Panel({
  title,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={clsx("rounded-lg border border-border-subtle bg-bg-1 overflow-hidden", className)}>
      {(title || actions) && (
        <div className="flex items-center gap-3 px-4 h-11 border-b border-border-subtle">
          {title && <h2 className="text-[length:var(--fs-14)] font-semibold text-text-1">{title}</h2>}
          {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
