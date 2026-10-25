"use client";

import { X } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, type ReactNode } from "react";

/**
 * Modal dialog on the native <dialog> element: focus is trapped and restored
 * by the browser, Escape closes it, and the rest of the page is inert.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  // Next.js keeps hidden routes mounted (React Activity): close when hidden.
  useLayoutEffect(() => {
    const dialog = ref.current;
    return () => {
      if (dialog?.open) dialog.close();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby={`${id}-title`}
      aria-describedby={description ? `${id}-description` : undefined}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose(); // click on the backdrop
      }}
      className="fixed inset-0 m-auto max-h-[calc(100dvh-2rem)] w-[min(calc(100vw-2rem),28rem)] overflow-y-auto rounded-[1.75rem] border border-line bg-surface p-0 text-ink shadow-card"
    >
      <div className="p-6">
        <div className="flex items-start justify-between gap-4">
          <h2 id={`${id}-title`} className="font-display text-2xl font-semibold leading-tight">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="-m-2 inline-flex size-11 shrink-0 items-center justify-center rounded-full text-muted hover:bg-surface-2"
            aria-label="Close"
          >
            <X aria-hidden className="size-5" />
          </button>
        </div>
        {description ? (
          <div id={`${id}-description`} className="mt-2 text-[0.95rem] text-muted">
            {description}
          </div>
        ) : null}
        <div className="mt-5">{children}</div>
      </div>
    </dialog>
  );
}
