import type { ReactNode, ButtonHTMLAttributes } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {
  X,
  Inbox,
  AlertCircle,
  ChevronRight,
  ChevronDown,
  LoaderCircle,
  type LucideIcon,
} from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
export const cn = (...values: Parameters<typeof clsx>) => twMerge(clsx(values));
export function Button({
  className,
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' }) {
  return <button className={cn('button', `button-${variant}`, className)} {...props} />;
}
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{children}</section>;
}
export function PanelHead({
  title,
  subtitle,
  action,
  icon: Icon,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div className="panel-head">
      <div>
        <h2>
          {Icon && <Icon size={20} aria-hidden="true" />}
          {title}
        </h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
export function PageTitle({
  title,
  description,
  actions,
  icon: Icon,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div className="page-title">
      <div>
        <h1>
          {Icon && <Icon className="page-title-icon" size={30} aria-hidden="true" />}
          {title}
        </h1>
        <p>{description}</p>
      </div>
      <div className="page-actions">{actions}</div>
    </div>
  );
}
export function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="disclosure">
      <summary>
        {title}
        <ChevronDown size={18} aria-hidden="true" />
      </summary>
      <div className="disclosure-content">{children}</div>
    </details>
  );
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Inbox size={25} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: string }) {
  return (
    <div className={`notice notice-${tone}`}>
      <AlertCircle size={17} />
      <div>{children}</div>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={27} />
      <span>Loading ICU research data…</span>
    </div>
  );
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className="modal">
          <Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{description}</Dialog.Description>
          <Dialog.Close className="modal-close" aria-label="Close dialog">
            <X size={20} />
          </Dialog.Close>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function ArrowLink({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button className="text-link" onClick={onClick}>
      {children}
      <ChevronRight size={16} />
    </button>
  );
}
export function Progress({ value }: { value: number }) {
  return (
    <div className="progress-track">
      <div
        className={value < 60 ? 'progress-fill warning' : 'progress-fill'}
        style={{ width: `${value}%` }}
      />
    </div>
  );
}
