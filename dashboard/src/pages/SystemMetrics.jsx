import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Panel from "../components/Panel";

export default function SystemMetrics({ history }) {
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title="CPU / Memory Chart" eyebrow="System Metrics">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history}>
              <defs>
                <linearGradient id="cpuFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#57a4ff" stopOpacity={0.5} />
                  <stop offset="95%" stopColor="#57a4ff" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="memoryFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3cf6d0" stopOpacity={0.5} />
                  <stop offset="95%" stopColor="#3cf6d0" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
              <XAxis dataKey="time" stroke="#8aa3bd" />
              <YAxis stroke="#8aa3bd" />
              <Tooltip contentStyle={{ background: "#0d1223", border: "1px solid rgba(255,255,255,0.1)" }} />
              <Area type="monotone" dataKey="cpu" stroke="#57a4ff" fill="url(#cpuFill)" />
              <Area type="monotone" dataKey="memory" stroke="#3cf6d0" fill="url(#memoryFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="Requests vs Errors Chart" eyebrow="Traffic">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
              <XAxis dataKey="time" stroke="#8aa3bd" />
              <YAxis stroke="#8aa3bd" />
              <Tooltip contentStyle={{ background: "#0d1223", border: "1px solid rgba(255,255,255,0.1)" }} />
              <Line type="monotone" dataKey="requests_per_min" stroke="#3cf6d0" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="errors_24h" stroke="#ff577f" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="AI Confidence Chart" eyebrow="Decisioning" className="xl:col-span-2">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
              <XAxis dataKey="time" stroke="#8aa3bd" />
              <YAxis domain={[0, 1]} stroke="#8aa3bd" />
              <Tooltip contentStyle={{ background: "#0d1223", border: "1px solid rgba(255,255,255,0.1)" }} />
              <Line type="monotone" dataKey="ai_confidence" stroke="#ffb347" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="patch_success_rate" stroke="#57a4ff" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>
    </div>
  );
}
