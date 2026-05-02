export function KillSwitchBanner({ reason }) {
  return (
    <div className="bg-red-600 text-white text-center py-2 px-4 font-semibold text-sm">
      KILL SWITCH ACTIVE: {reason || 'Emergency stop triggered'}
    </div>
  );
}
