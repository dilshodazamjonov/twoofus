import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "./cn";
import { Spinner } from "./spinner";

type Variant = "primary" | "secondary" | "soft" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const base =
  "inline-flex select-none items-center justify-center gap-2 rounded-full font-medium tracking-[0.005em] " +
  "transition-[background-color,color,box-shadow,transform] duration-200 active:scale-[0.98] " +
  "disabled:pointer-events-none disabled:opacity-55 touch-manipulation";

// Every size keeps a touch target of at least 44 px.
const sizes: Record<Size, string> = {
  sm: "min-h-11 px-4 text-sm",
  md: "min-h-11 px-5 text-[0.95rem]",
  lg: "min-h-12 px-6 text-base",
};

const variants: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink shadow-soft hover:bg-accent-hover",
  secondary: "border border-line-strong/50 bg-surface text-ink hover:bg-surface-2",
  soft: "bg-accent-soft text-accent-text hover:bg-accent-soft/70",
  ghost: "text-accent-text hover:bg-accent-soft/60",
  danger: "bg-danger text-danger-ink hover:opacity-90",
};

export function buttonClasses(variant: Variant = "primary", size: Size = "md", className?: string): string {
  return cn(base, sizes[size], variants[variant], className);
}

type ButtonProps = ComponentProps<"button"> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={buttonClasses(variant, size, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

type ButtonLinkProps = ComponentProps<typeof Link> & { variant?: Variant; size?: Size; icon?: ReactNode };

export function ButtonLink({ variant = "primary", size = "md", icon, className, children, ...props }: ButtonLinkProps) {
  return (
    <Link className={buttonClasses(variant, size, className)} {...props}>
      {icon}
      {children}
    </Link>
  );
}
