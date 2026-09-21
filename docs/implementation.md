# Thiết kế TSP-SAT + CEGAR

## Pipeline

Parser tạo `SSPInstance` với requirement set của từng job. `preprocess_dominance`
giữ các representative inclusion-maximal; sequence sau khi solve được
reconstruct về đầy đủ job gốc. `construct_upper_bound` vẫn dùng all-start
greedy trên reduced instance rồi chạy KTNS trên full sequence. Lower bound là
`max(C, |union R_i|)`.

Solver chạy trên `ReducedInstance`. Với `N` active jobs, dummy có vertex `0`
và real job local `i` dùng vertex `i + 1`.

## Formula

Các primary variable là:

- `x[i,j]`, `i != j`: vertex `j` đứng ngay sau `i`;
- `z[u,j]`: tool `u` nằm trong magazine tại real vertex `j`;
- `t[u,j]`: tool `u` được insert khi đi tới real vertex `j`.

Mọi named variable được cấp trước khi cardinality encoder cấp auxiliary
variable qua cùng `IDPool`.

Hai equality degree cho mỗi vertex đảm bảo đúng một incoming và outgoing arc.
Capacity của mỗi real vertex là `sum_u z[u,j] = C`; requirements là unit
clauses. Các equality này dùng `CardEnc.equals(..., EncType.seqcounter)`.

Nếu `i,j` đều là real vertex, cho mọi tool `u` formula thêm:

```text
x[i,j] -> (t[u,j] <-> (z[u,j] and not z[u,i]))
```

Với dummy rỗng, arc `0 -> j` dùng `t[u,j] <-> z[u,j]`. Không có transition
constraint trên arc quay về dummy.

Objective là tổng toàn bộ `t[u,j]`. Chỉ objective dùng `ITotalizer`. Nếu
`rhs[k]` là output “ít nhất `k + 1` insertions”, assumption `-rhs[k]` biểu
diễn `T <= k`. ITotalizer và base clauses chỉ được tạo một lần cho mỗi
instance.

## CEGAR và tối ưu

Degree constraints chỉ tạo cycle cover. Sau mỗi SAT model, `decode_successor`
phân rã successor permutation thành directed cycles. Với mọi cycle `S` không
chứa dummy, solver nhận cut:

```text
or x[i,j]  for i in S, j not in S
```

Tất cả bad cycles của cùng model được thêm trước SAT call kế tiếp. CaDiCaL
chạy trong một `IncrementalSolverSession`; base clauses, ITotalizer,
subtour cuts và learned clauses không bị reset.

Search bắt đầu tại `UB - 1`. Một Hamiltonian model được kiểm chứng độc lập,
đếm actual `t` cost `q`, rồi search chuyển trực tiếp sang `q - 1`. UNSAT đầu
tiên chứng minh incumbent; nếu next bound nhỏ hơn lower bound thì lower bound
là certificate tương đương. Timeout đóng worker và chỉ trả incumbent khả thi.

## Verifier và reporting

`validate_tsp_solution` không tin encoder: nó kiểm tra Hamiltonian sequence,
requirements, magazine capacity, initial load, từng transition set và cost
từ `t`. Sau đó nó reconstruct full sequence, chạy KTNS, và kiểm tra full KTNS
cost không lớn hơn decoded SAT policy. Magazine sets và inserted-tool sets
được giữ trong `ValidationResult` để debug.

Mỗi SAT call log `k`, CEGAR round, status, số subtour/cut, formula size,
solve time, CaDiCaL stats và actual Hamiltonian cost khi có. CSV tổng hợp số
solver calls, CEGAR rounds và total subtour cuts.

## Module layout

```text
parser.py       input validation and discovery
dominance.py    reduction and reconstruction
upper_bound.py  all-start greedy + KTNS upper bound
encoding.py     x/z/t TSP formula and ITotalizer
subtour.py      successor decoding, cycle detection and CEGAR cuts
solver.py       persistent, time-limited CaDiCaL process
validate.py     independent model verification
optimize.py     descending incremental CEGAR search
report.py       console and CSV output
```
