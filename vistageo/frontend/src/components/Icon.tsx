import type { SVGProps } from 'react'

export type IconName = 'home' | 'register' | 'search' | 'camera' | 'photos' | 'users' | 'roles' | 'locations' | 'menu' | 'close' | 'collapse' | 'expand' | 'logout' | 'arrow'

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  const paths: Record<IconName, React.ReactNode> = {
    home: <><path d="m3 10 9-7 9 7" /><path d="M5 9v11h14V9M9 20v-6h6v6" /></>,
    register: <><path d="M12 21s-6.5-5.3-6.5-11a6.5 6.5 0 0 1 13 0c0 5.7-6.5 11-6.5 11Z" /><path d="M12 7v6M9 10h6" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 4 4" /></>,
    camera: <><path d="M4 8h3l1.5-2h7L17 8h3v11H4z" /><circle cx="12" cy="13.5" r="3" /></>,
    photos: <><rect x="4" y="5" width="16" height="14" rx="2" /><circle cx="9" cy="9" r="1" /><path d="m5 17 4-4 3 3 2-2 5 4" /></>,
    users: <><circle cx="9" cy="8" r="3" /><path d="M3.5 20v-2a5.5 5.5 0 0 1 11 0v2M16 5.5a3 3 0 0 1 0 5.8M17 13a5 5 0 0 1 3.5 5v2" /></>,
    roles: <><path d="M12 3 5 6v5c0 4.5 2.8 7.7 7 10 4.2-2.3 7-5.5 7-10V6z" /><path d="m9 12 2 2 4-4" /></>,
    locations: <><path d="M12 21s-6.5-5.3-6.5-11a6.5 6.5 0 0 1 13 0c0 5.7-6.5 11-6.5 11Z" /><circle cx="12" cy="10" r="2" /></>,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    collapse: <><path d="M4 5h16v14H4zM9 5v14" /><path d="m15 9-3 3 3 3" /></>,
    expand: <><path d="M4 5h16v14H4zM9 5v14" /><path d="m13 9 3 3-3 3" /></>,
    logout: <><path d="M10 4H5v16h5M14 8l4 4-4 4M8 12h10" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  }
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>
}
