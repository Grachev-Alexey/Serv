import { ButtonHTMLAttributes, forwardRef } from "react";

type Variant = "primary" | "ghost" | "subtle" | "danger";
type Size = "sm" | "md" | "icon";

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 disabled:opacity-50 disabled:pointer-events-none select-none";

const variants: Record<Variant, string> = {
  primary: "bg-brand text-white hover:bg-brand-hover shadow-sm shadow-brand/30",
  ghost: "text-ink-muted hover:text-ink hover:bg-white/5",
  subtle: "bg-white/[0.04] text-ink hover:bg-white/[0.08] ring-1 ring-hairline",
  danger: "bg-danger/10 text-danger hover:bg-danger/20 ring-1 ring-danger/30",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-sm",
  icon: "h-9 w-9",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = forwardRef<HTMLButtonElement, Props>(
  ({ variant = "primary", size = "md", className = "", ...props }, ref) => (
    <button
      ref={ref}
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    />
  ),
);
Button.displayName = "Button";
