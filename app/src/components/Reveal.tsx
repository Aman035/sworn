'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Reveals a section once, the first time it comes into view.
 *
 * Deliberately one effect, used on section containers only: a fade-and-slide on every
 * card is the tell of a page that mistakes motion for design. This exists so the page has
 * a sense of unfolding as you read down it, and it never repeats.
 *
 * Under `prefers-reduced-motion`, and with JavaScript off, content is visible from the
 * start: the animation is decoration, never the thing that makes the page readable.
 */
export function Reveal({
  as: Tag = 'div',
  className = '',
  children,
}: {
  as?: 'div' | 'section';
  className?: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setShown(true);
            io.disconnect();
          }
        }
      },
      { rootMargin: '0px 0px -12% 0px' },
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);

  return (
    <Tag
      ref={ref as never}
      className={`${className} reveal${shown ? ' in' : ''}`.trim()}
      data-reveal=""
    >
      {children}
    </Tag>
  );
}
