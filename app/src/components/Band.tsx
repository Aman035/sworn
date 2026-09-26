import type { Meta } from '@/lib/results';
import { Rail } from './Rail';

export function Band({
  meta,
  extra,
  children,
}: {
  meta: Meta | null;
  extra?: [string, string][] | undefined;
  children: React.ReactNode;
}) {
  return (
    <section className="band">
      {/* Content first. The provenance line is a citation, and a citation goes after the
          thing it supports. */}
      <div className="body">{children}</div>
      <Rail meta={meta} extra={extra} />
    </section>
  );
}

export function Missing({ pipeline }: { pipeline: string }) {
  return (
    <div className="caveat">
      <p>
        Not computed. Run <code className="addr">{pipeline}</code> to produce it. This page shows
        nothing rather than zeros, because a zero here would read as a measurement.
      </p>
    </div>
  );
}
