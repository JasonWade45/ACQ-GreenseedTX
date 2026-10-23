// Re-mounts on every navigation → each page transition gets a soft entrance.
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="anim-in">{children}</div>;
}
