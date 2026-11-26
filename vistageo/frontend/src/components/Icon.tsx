import {
  ArrowRight,
  Camera,
  House,
  Images,
  LogOut,
  MapPin,
  MapPinPlus,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  ShieldCheck,
  UsersRound,
  X,
  type LucideIcon,
} from 'lucide-react'
import type { SVGProps } from 'react'

export type IconName = 'home' | 'register' | 'search' | 'camera' | 'photos' | 'users' | 'roles' | 'locations' | 'menu' | 'close' | 'collapse' | 'expand' | 'logout' | 'arrow'

const icons: Record<IconName, LucideIcon> = {
  home: House,
  register: MapPinPlus,
  search: Search,
  camera: Camera,
  photos: Images,
  users: UsersRound,
  roles: ShieldCheck,
  locations: MapPin,
  menu: Menu,
  close: X,
  collapse: PanelLeftClose,
  expand: PanelLeftOpen,
  logout: LogOut,
  arrow: ArrowRight,
}

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  const IconComponent = icons[name]
  return <IconComponent aria-hidden="true" focusable="false" strokeWidth={1.75} {...props} />
}
