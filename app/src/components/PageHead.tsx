/**
 * The top of an interior page.
 *
 * The landing opens on a full-bleed dark hero; without an equivalent, the data pages
 * started abruptly under a floating nav with a row of hashes as the first thing on
 * screen. This gives them the same opening register. Eyebrow, large title, one line of
 * standfirst, so the site reads as one product rather than a landing page bolted to a
 * set of tables.
 */
export function PageHead({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="pagehead">
      <div className="pagehead-inner">
        <p className="hero-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {children ? <p className="pagehead-sub">{children}</p> : null}
      </div>
    </header>
  );
}
