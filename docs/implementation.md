# Thiết kế các bộ giải SAT cho SSP

## Pipeline và chi phí

CLI bắt buộc chọn `direct-sat`, `tsp-sat-cegar` hoặc `job-grouping-sat`; Python API bắt buộc
keyword `algorithm` của `optimize_instance`. Cả hai dùng khay ban đầu rỗng,
sức chứa tối đa C và đếm tổng số dụng cụ lắp, kể cả bước đầu.

Dominance giữ các công việc có tập yêu cầu inclusion-maximal, ánh xạ lại ID
công việc và dụng cụ. Dụng cụ không dùng không có biến SAT hay chi phí filler.
Công việc bị loại được khôi phục ngay sau đại diện, có thể dùng cùng khay.

UB sắp công việc giảm dần theo tổng tần suất dụng cụ trong reduced instance;
hòa điểm chọn ID công việc gốc nhỏ hơn. Mỗi bước lắp dụng cụ thiếu, rồi tháo
dụng cụ không cần theo ID gốc giảm dần nếu vượt C. UB lưu đúng chi phí và
khay greedy, kể cả khay lặp cho công việc bị loại. LB là số dụng cụ khác nhau
được yêu cầu. KTNS bắt đầu rỗng, lắp khi thiếu, chỉ tháo khi cần chỗ và ưu tiên
tháo dụng cụ có lần dùng tiếp theo xa nhất.

## Encoding direct

`DirectBuildResult` lưu `x[job,position]`, `z[tool,position]`,
`t[tool,position]` với ID local bắt đầu từ 0. Mỗi công việc có đúng một vị trí,
mỗi vị trí đúng một công việc. Assignment dùng sequential counter; khay dùng
`CardEnc.atmost` với sequential counter. `x` kéo theo các dụng cụ bắt buộc.

Công việc đầu tiên của greedy chỉ được xuất hiện trong ceil(N/2) vị trí đầu.
Các vị trí nửa sau bị cấm bằng unit clauses; equality của công việc vẫn áp
dụng trên toàn bộ vị trí. Mọi thứ tự hoặc thứ tự đảo của nó đều có công việc
mốc trong nửa đầu. Chi phí tối ưu bảo toàn dưới phép đảo: với các khay khả thi,
tổng số lần lắp bằng một nửa tổng kích thước hai khay đầu/cuối cộng tổng
kích thước các symmetric difference giữa khay liên tiếp.

`t[u,0] <-> z[u,0]`; các bước sau:
`t[u,p] <-> (z[u,p] and not z[u,p-1])`. Không dùng dummy hoặc CEGAR.

## Encoding TSP và tìm kiếm

TSP giữ dummy rỗng 0, real vertex i+1 và adjacency `x[i,j]`. Degree equalities
tạo cycle cover. Khay mỗi vertex chứa yêu cầu và tối đa min(C,U) dụng cụ.
Arc được chọn xác định chính xác tập lắp giữa hai khay; arc từ dummy tính
mọi dụng cụ trong khay đầu. Không tính chi phí quay về dummy.

Sau SAT, các cycle không chứa dummy nhận subtour-exit cut trước lần gọi tiếp.
TSP dùng một `IncrementalSolverSession` CaDiCaL cùng `ITotalizer` và assumption
`-rhs[k]` để áp đặt tổng lắp <= k. Direct tạo `CardEnc.atmost(t, k,
EncType.seqcounter)` và một CaDiCaL session fresh cho từng bound. Counter luôn
bắt đầu ở các auxiliary ID sau base formula; solver, learned clauses và counter
cũ bị hủy trước bound tiếp theo. Direct không tạo totalizer.

Tìm kiếm bắt đầu UB-1. Validator kiểm tra độc lập thứ tự, khay, tập lắp và
bound; direct kiểm tra thêm công việc mốc, TSP kiểm tra Hamiltonian cycle.
KTNS trên full sequence không được đắt hơn nghiệm SAT. Incumbent tốt nhất
quyết định bound tiếp theo. UNSAT chứng minh tối ưu; đạt LB cũng chứng minh
tối ưu. Nếu timeout, worker được dọn và trả incumbent mà không nhận tối ưu.
Yêu cầu rỗng toàn bộ có UB=LB=0 và không cần solver.

## Báo cáo

Console và CSV giữ tên thuật toán, UB greedy, cost, formula size, solver calls
và CaDiCaL statistics. Direct có CEGAR rounds, subtour cuts bằng 0. KTNS
verification cost có thể nhỏ hơn greedy incumbent khi timeout; best cost
vẫn là chi phí của khay được lưu. Các cột CSV hiện tại được giữ nguyên.

## Job Grouping SAT

`job-grouping-sat` uses a separate objective: the initial magazine is free,
and cost sums `|M[g] - M[g-1]|` only for `g > 0`. `ktns_switches` leaves the
legacy `ktns` semantics intact and is checked against an independent oracle
that enumerates magazine states. For a fixed sequence, the cost equals
`legacy_cost - min(C, number of distinct required tools)`.

Its lower bound is `max(0, U-C)`. The feasible upper-bound sequence is
reevaluated with `ktns_switches`, after dominance preprocessing reconstructs
the full sequence.

Each bound `K` builds a fresh CNF and `IDPool` with `G=min(n,K+1)`. All primary
variables are allocated before auxiliaries. Assignment, capacity, clique, and
objective cardinalities use sequential counters. Each bound is solved once by
a fresh `cadical300` worker, which is then destroyed. No clauses or learned
state carry into the next bound.

`basic` uses the exact grouping model. `symmetry` adds the earliest-compatible-
group rule. `clique` adds at-most-one-per-group constraints for up to 100
deterministically discovered incompatibility cliques. Exact capacity clauses
remain active in all configurations.

The CLI atomically saves each completed instance to CSV, including objective
version, dataset and configuration fingerprints, and the incumbent sequence.
`--resume` skips committed instances and rejects an incompatible checkpoint.
The parser verifies 1,350 current Yanasse inputs: A=340, B=330, C=340, D=260,
E=80. The 2026 C-B&B paper reports 1,390 total and 370 in B. Its cited public
HGS-SSP source (`jordanamecler/HGS-SSP`, `Instances/Yanasse`) has the same 330
B files, and their checksums match this checkout. The extra 40 B instances
remain unaccounted for; runs are incomplete relative to the paper's reported
count. No synthetic inputs were created.

For objective comparison, Locatelli et al. define sequence cost as the sum of
magazine insertions from the second job onward, so their C-B&B values use the
same initial-load-free convention; no offset is needed. Their experiment used
an Apple M3/16 GB machine, macOS 26, and a 1,200-second per-instance limit. The
paper reports 1,390/1,390 optimal Yanasse results and group average times of
0.00, 0.00, 0.07, 15.63, and 0.02 seconds for A–E. These are published
aggregate reference values, not a hardware-normalized comparison.

References: [Akhundov and Ostrowski (2024), DOI 10.1016/j.ejor.2024.02.030](https://doi.org/10.1016/j.ejor.2024.02.030);
[Locatelli, Côté, and Coelho (2026), arXiv:2609.03219](https://arxiv.org/abs/2609.03219).
