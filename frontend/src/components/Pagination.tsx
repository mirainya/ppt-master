import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  page: number;
  pageCount: number;
  total: number;
  rangeStart: number;
  rangeEnd: number;
  unitLabel?: string;
  onPage: (page: number) => void;
}

/**
 * Compact numeric pager: first / last always shown, current page centered,
 * gaps collapsed to an ellipsis. Reusable across any paginated table.
 */
function pageItems(page: number, pageCount: number): (number | "gap")[] {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, i) => i + 1);
  }
  const items: (number | "gap")[] = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(pageCount - 1, page + 1);
  if (start > 2) items.push("gap");
  for (let p = start; p <= end; p += 1) items.push(p);
  if (end < pageCount - 1) items.push("gap");
  items.push(pageCount);
  return items;
}

export function Pagination({
  page,
  pageCount,
  total,
  rangeStart,
  rangeEnd,
  unitLabel = "条",
  onPage,
}: PaginationProps) {
  const items = pageItems(page, pageCount);

  return (
    <div className="table-pagination">
      <span className="page-info">
        {total > 0
          ? `${rangeStart}–${rangeEnd} / 共 ${total} ${unitLabel}`
          : `暂无${unitLabel === "条" ? "数据" : unitLabel}`}
      </span>

      <div className="pager">
        <button
          type="button"
          className="pager-nav"
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
          aria-label="上一页"
          title="上一页"
        >
          <ChevronLeft size={16} />
        </button>

        {items.map((item, index) =>
          item === "gap" ? (
            <span key={`gap-${index}`} className="pager-gap">
              …
            </span>
          ) : (
            <button
              key={item}
              type="button"
              className={`pager-page ${item === page ? "active" : ""}`}
              onClick={() => onPage(item)}
              aria-label={`第 ${item} 页`}
              aria-current={item === page ? "page" : undefined}
            >
              {item}
            </button>
          ),
        )}

        <button
          type="button"
          className="pager-nav"
          onClick={() => onPage(page + 1)}
          disabled={page >= pageCount}
          aria-label="下一页"
          title="下一页"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
