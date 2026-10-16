import type { ReactNode } from "react";
import { Icon } from "../../components/Icon";

export function HelpText({ children }: { children: ReactNode }) {
  return (
    <div className="help-text">
      <Icon name="info" />
      <div>{children}</div>
    </div>
  );
}
