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
      <Rail meta={meta} extra={extra} />
      <div className="body">{children}</div>
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
