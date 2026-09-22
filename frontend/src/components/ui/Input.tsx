import { InputHTMLAttributes, ReactNode, forwardRef } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode;
  trailing?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, Props>(
  ({ icon, trailing, className = "", ...props }, ref) => (
    <div className="relative">
      {icon && (
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint">
          {icon}
        </span>
      )}
      <input
        ref={ref}
        className={`h-11 w-full rounded-lg bg-black/25 text-ink ring-1 ring-hairline placeholder:text-ink-faint outline-none transition focus:ring-2 focus:ring-brand/60 ${
          icon ? "pl-10" : "pl-3.5"
        } ${trailing ? "pr-10" : "pr-3.5"} ${className}`}
        {...props}
      />
      {trailing && (
        <span className="absolute right-2 top-1/2 -translate-y-1/2">{trailing}</span>
      )}
    </div>
  ),
);
Input.displayName = "Input";
