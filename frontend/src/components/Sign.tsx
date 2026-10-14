/**
 * The motel sign, doubling as the status bar.
 *
 * The sign is "lit" only while the backend answers. If uvicorn is not running
 * the neon goes dark and the vacancy line changes — so the one piece of
 * decoration on the page is also the health indicator, and you learn the
 * backend is down by looking at the thing you were already looking at.
 */

interface Props {
  online: boolean;
  shopDate: string | null;
  balance: number | null;
  openCount: number;
  resolvedCount: number;
}

export function Sign({ online, shopDate, balance, openCount, resolvedCount }: Props) {
  return (
    <header className={`sign${online ? " lit" : ""}`}>
      <div className="sign-mark">
        <h1>Rosebud</h1>
        <span className="vacancy">
          <span className="bulb" />
          {online ? "Operations desk — open" : "back office unreachable"}
        </span>
      </div>

      <div className="sign-meta">
        <div className="sign-stat">
          <dt>Shop date</dt>
          <dd>{shopDate ?? "—"}</dd>
        </div>
        <div className="sign-stat">
          <dt>On the board</dt>
          <dd>
            {openCount} open · {resolvedCount} closed
          </dd>
        </div>
        <div className="sign-stat">
          <dt>Checking</dt>
          <dd>
            {balance == null
              ? "—"
              : balance.toLocaleString("en-US", { style: "currency", currency: "USD" })}
          </dd>
        </div>
      </div>
    </header>
  );
}
