import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ClipboardList,
  Search,
  Settings2,
  Upload,
  UserRound,
} from "lucide-react";
import { api } from "./api";
import { Badge, Modal } from "./components";
import type { LeadPage } from "./types";

export default function SearchPalette({ onClose }: { onClose: () => void }) {
  const [term, setTerm] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(term.trim()), 250);
    return () => clearTimeout(timer);
  }, [term]);
  const results = useQuery({
    queryKey: ["command-search", query],
    queryFn: () =>
      api<LeadPage>(`/leads?search=${encodeURIComponent(query)}&page_size=7`),
    enabled: query.length >= 2,
  });
  return (
    <Modal
      title="Find your next move"
      subtitle="Search your local workspace. No information is sent to AI."
      onClose={onClose}
    >
      <div className="command-search">
        <Search size={22} />
        <input
          data-autofocus="true"
          aria-label="Search workspace"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="Seller name, phone, property, external ID…"
        />
        <kbd>ESC</kbd>
      </div>
      <div className="command-content">
        {query.length >= 2 ? (
          <>
            <div className="command-caption">
              SELLER RESULTS {results.isFetching && <span>Searching…</span>}
            </div>
            {results.isError ? (
              <div className="command-empty" role="alert">
                Search is unavailable. Try again from the Leads screen.
              </div>
            ) : (
              results.data?.items.map((lead) => (
                <Link
                  className="command-result"
                  to={`/leads/${lead.id}`}
                  onClick={onClose}
                  key={lead.id}
                >
                  <span className="command-avatar">
                    <UserRound size={19} />
                  </span>
                  <span>
                    <strong>
                      {lead.full_name || "Owner identity unknown"}
                    </strong>
                    <small>
                      {lead.properties[0]?.street_address ||
                        "Property address not recorded"}
                    </small>
                  </span>
                  <Badge>{lead.stage_code.replaceAll("_", " ")}</Badge>
                  <ArrowRight size={16} />
                </Link>
              ))
            )}
            {!results.isFetching && results.data?.total === 0 && (
              <div className="command-empty">
                No matching sellers. Try another name, address or phone.
              </div>
            )}
          </>
        ) : (
          <>
            <div className="command-caption">QUICK NAVIGATION</div>
            {[
              {
                to: "/followups",
                label: "Open daily follow-ups",
                detail: "Your next tasks, with evidence",
                icon: ClipboardList,
              },
              {
                to: "/imports",
                label: "Import seller leads",
                detail: "Review and approve a spreadsheet",
                icon: Upload,
              },
              {
                to: "/settings#connections",
                label: "Connections & private keys",
                detail: "Configure reviewed Groq and read-only CRM",
                icon: Settings2,
              },
            ].map((item) => (
              <Link
                className="command-result"
                key={item.to}
                to={item.to}
                onClick={onClose}
              >
                <span className="command-avatar">
                  <item.icon size={19} />
                </span>
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </span>
                <ArrowRight size={16} />
              </Link>
            ))}
          </>
        )}
      </div>
      <div className="command-footer">
        <span>Type at least 2 characters to search</span>
        <span>
          <kbd>Ctrl</kbd> + <kbd>K</kbd> to open
        </span>
      </div>
    </Modal>
  );
}
