import { Link } from 'react-router-dom';

export default function SettingsEntry() {
  return (
    <Link className="header-icon-action settings-entry" to="/settings" aria-label="打开设置" title="设置">
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M9.67 3.3h4.66l.55 2.18c.5.19.97.46 1.4.78l2.14-.67 2.33 4.04-1.6 1.57c.04.26.06.53.06.8s-.02.54-.06.8l1.6 1.57-2.33 4.04-2.14-.67c-.43.32-.9.59-1.4.78l-.55 2.18H9.67l-.55-2.18a7.1 7.1 0 0 1-1.4-.78l-2.14.67-2.33-4.04 1.6-1.57a5.8 5.8 0 0 1 0-1.6l-1.6-1.57 2.33-4.04 2.14.67c.43-.32.9-.59 1.4-.78l.55-2.18Z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    </Link>
  );
}
