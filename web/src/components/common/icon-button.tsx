import type { ReactNode } from "react";

import { Button, type ButtonProps } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface IconButtonProps {
  label: string;
  children: ReactNode;
  onClick?: ButtonProps["onClick"];
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  disabled?: boolean;
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
  type?: "button" | "submit";
}

/** 图标按钮 + Tooltip：保证 aria-label 与可见焦点环，图标仅装饰。 */
export function IconButton({
  label,
  children,
  onClick,
  variant = "ghost",
  size = "icon-sm",
  disabled,
  className,
  side = "bottom",
  type = "button",
}: IconButtonProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type={type}
          variant={variant}
          size={size}
          aria-label={label}
          onClick={onClick}
          disabled={disabled}
          className={className}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side={side}>{label}</TooltipContent>
    </Tooltip>
  );
}
