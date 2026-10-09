import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center whitespace-nowrap rounded border px-2.5 py-1 text-xs font-semibold",
  {
    variants: {
      variant: {
        default: "border-teal-400/25 bg-teal-400/10 text-teal-800",
        secondary: "border-slate-500/25 bg-slate-500/10 text-secondary",
        destructive: "border-red-400/25 bg-red-400/10 text-red-800",
        outline: "border-line bg-transparent text-secondary",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
