# Thiết kế direct-SAT và TSP-SAT + CEGAR

## Pipeline và chi phí

CLI bắt buộc `--algorithm direct-sat|tsp-sat-cegar`; Python API bắt buộc
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
Hai thuật toán dùng cùng một `IncrementalSolverSession` CaDiCaL. TSP dùng
`ITotalizer` và assumption `-rhs[k]` để áp đặt tổng lắp <= k. Direct thêm
`CardEnc.atmost(t, k, EncType.seqcounter)` mới vào solver cho mỗi bound; các
ràng buộc bound cũ được giữ lại và trở nên dư thừa khi bound giảm. Direct không
tạo totalizer.

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
