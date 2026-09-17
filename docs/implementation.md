# Tài liệu triển khai SSP SAT Solver

## 1. Tổng quan

Dự án giải chính xác bài toán Job Sequencing and Tool Switching Problem (SSP)
bằng SAT. Mục tiêu là tìm một hoán vị của các job sao cho tổng số lần nạp tool
vào magazine là nhỏ nhất. Chi phí bao gồm cả `c` lần nạp để tạo magazine ban
đầu.

Pipeline hiện tại:

```text
đọc input
  -> dominance preprocessing
  -> tính lower bound và pairwise distance
  -> all-start greedy + KTNS để lấy upper bound
  -> linear descending SAT search
  -> decode và kiểm tra model độc lập
  -> reconstruction về đầy đủ original jobs
  -> KTNS verification
  -> console + CSV
```

Chương trình hỗ trợ hai chế độ tối ưu:

- `standard`: tạo CNF và một CaDiCaL worker mới cho từng bound;
- `incremental`: tạo một `ITotalizer`, giữ một CaDiCaL worker và learned state
  xuyên suốt các bound của một problem.

CaDiCaL luôn chạy trong process riêng để chương trình có thể tự quản lý timeout
và `KeyboardInterrupt`. Chương trình không dùng time-limit API của PySAT.

## 2. Cài đặt và chạy

Yêu cầu:

- Python `>=3.11`;
- `python-sat` có backend `cadical300`.

Đồng bộ môi trường và chạy console entry point:

```bash
uv sync
uv run ssp-sat data/dummy.txt
```

Hoặc chạy bằng package Python từ repository:

```bash
.venv/bin/python -m src data/dummy.txt
```

Cú pháp CLI:

```text
ssp-sat [-h] [--limit SECONDS] [--incremental]
        [--csv CSV | --no-csv] input
```

Các tham số:

- `input`: một benchmark file hoặc một thư mục. Thư mục được quét đệ quy theo
  thứ tự đường dẫn ổn định;
- `--limit SECONDS`: tổng time limit cho mỗi problem, mặc định `600` giây;
- `--incremental`: bật chế độ Incremental SAT; nếu không có cờ này thì dùng
  standard mode;
- `--csv PATH`: chỉ định đường dẫn CSV;
- `--no-csv`: không tạo CSV.

Ví dụ:

```bash
uv run ssp-sat data/Catanzaro/datA1 --limit 120
uv run ssp-sat data/Catanzaro/datA1 --incremental
uv run ssp-sat data --incremental --csv benchmark.csv
```

Project được khai báo trong `pyproject.toml` với distribution name `ssp-sat`,
package import là `src`, và console entry point là `ssp-sat = src.cli:main`.

## 3. Input và parser

Một file có metadata dùng chung và một hoặc nhiều problem block:

```text
n=10
m=10
c=4

problem 1:
---------
0 1 ...
...
```

Parser duy nhất hỗ trợ cả `problem N:` và `problem N`. Khoảng trắng quanh dấu
`=` được chấp nhận. Matrix có `m` hàng và `n` cột:

- mỗi hàng là một tool;
- mỗi cột là một job;
- `R_i` được dựng từ cột `i`.

Chỉ `n`, `m`, `c` có ý nghĩa. Các dòng sau bị bỏ qua hoàn toàn:

- `min=...`;
- `max=...`;
- `best known value ...`;
- dòng trống và separator chỉ gồm dấu `-`.

Best-known value không được lưu và không tham gia upper bound, lower bound,
validation hay test optimum.

Parser kiểm tra:

- đủ metadata `n`, `m`, `c` và không có giá trị mâu thuẫn;
- `n,m > 0` và `1 <= c <= m`;
- problem ID duy nhất, liên tiếp và bắt đầu từ `1`;
- mỗi problem có đúng `m` hàng Boolean;
- mỗi hàng có đúng `n` giá trị `0/1`;
- mọi job thỏa `|R_i| <= c`.

Tên instance ổn định có dạng `relative-path#problem-N`. Parser đã được smoke
test trên toàn bộ dữ liệu hiện có: 168 file và 1.671 instances.

## 4. Mô hình dữ liệu

Các record chính nằm trong `src/model.py`:

- `SSPInstance`: original matrix, requirements và metadata nguồn;
- `ReducedInstance`: requirements của active representatives sau dominance;
- `DominanceResult`: active jobs, hai chiều local/original mapping và mapping
  các job bị loại;
- `CNFBuildResult`: CNF, `IDPool`, toàn bộ variable maps, thống kê và output
  của `ITotalizer` khi có;
- `SolverResult`: `SAT`, `UNSAT` hoặc `TIMEOUT`, model, solve time và stats;
- `IterationResult`: kết quả của một bound;
- `OptimizationResult`: mode, bounds, status, sequences, optimum/best cost và
  timing của một problem.

Job/tool ID dùng zero-based. Position trong SAT dùng one-based.

## 5. Dominance preprocessing và reconstruction

Nếu `R_i` là tập con của `R_h`, job `i` có thể được gắn vào representative
`h`. Cách triển khai tránh mapping theo chain:

1. group các job có requirement set giống nhau;
2. tìm các requirement set inclusion-maximal;
3. giữ job ID nhỏ nhất làm canonical representative của mỗi maximal set;
4. ánh xạ trực tiếp mọi job còn lại tới một active representative.

Khi có nhiều representative chứa `R_i`, chọn deterministic theo:

```text
(số tool của representative, original job ID)
```

Reconstruction thay mỗi representative `h` trong reduced sequence bằng:

```text
[các dominated job của h theo ID tăng dần, h]
```

Assertions bảo đảm mỗi original job xuất hiện đúng một lần và mỗi dominated
requirement thực sự là tập con của representative requirement.

## 6. Bounds, greedy và KTNS

Lower bound:

```math
LB = \max\left(c, \left|\bigcup_i R_i\right|\right).
```

Trên reduced instance, pairwise distance là:

```math
d_{i,h}=\max(0,|R_i\cup R_h|-c).
```

Upper bound được tạo bằng all-start greedy. Với mỗi active starting job, job
tiếp theo tối thiểu hóa tuple:

```text
(d[i][h], -|R_i intersection R_h|, original job ID)
```

Reduced sequence được reconstruct trước khi đánh giá bằng KTNS trên original
instance. Khi nhiều sequence có cùng cost, chọn full sequence nhỏ hơn theo thứ
tự từ điển.

KTNS:

- precompute next-use table bằng một lượt backward;
- magazine đầu chứa requirements của first job và được lấp đủ `c` bằng các
  tool có next use gần nhất;
- initial cost là `c`;
- tại mỗi job sau, nạp các missing required tools và loại đúng số tool tương
  ứng có next use xa nhất;
- tool không còn được dùng có next use vô cực và bị loại trước;
- tie được xử lý bằng tool ID để kết quả deterministic.

KTNS trả cả cost và magazine configuration tại từng position.

## 7. SAT encoding

SAT chỉ encode reduced instance và sử dụng một `IDPool` chung.

### 7.1 Variables

- `x[i,j]`: job local `i` nằm chính xác tại position `j`;
- `y[i,j]`: order/transition representation của vị trí job;
- `z[u,j]`: tool `u` nằm trong magazine tại position `j`;
- `t[u,j]`: tool `u` được insert khi chuyển tới position `j`;
- `s[q,r,j]`: trong `q` tool đầu tiên có ít nhất `r` tool trong magazine.

### 7.2 Job permutation

Mỗi job có boundary:

```math
y_{i,1}=1,\qquad y_{i,N'+1}=0
```

và monotonicity `y[i,j+1] -> y[i,j]`. Liên kết:

```math
x_{i,j}\leftrightarrow(y_{i,j}\land\neg y_{i,j+1}).
```

Không có exactly-one cardinality theo từng job. At-most-one job cho mỗi
position được encode bằng:

```python
CardEnc.atmost(
    lits=position_literals,
    bound=1,
    vpool=vpool,
    encoding=EncType.seqcounter,
)
```

Kết hợp structural job encoding và position AMO tạo thành một permutation.

### 7.3 Job requirements và magazine capacity

Với `u in R_i`:

```math
x_{i,j}\rightarrow z_{u,j}.
```

Magazine luôn chứa đúng `c` tools. Exact capacity được encode bằng custom
order-counter `s`, gồm boundary, impossible states `r>q`, recurrence hai chiều
và hai unit clauses:

```math
s_{m,c,j}=1,\qquad s_{m,c+1,j}=0.
```

Magazine ban đầu trước position 1 rỗng:

```math
z_{u,0}=0.
```

### 7.4 Tool insertions và strengthening

Insertion variables thỏa equivalence:

```math
t_{u,j}\leftrightarrow(z_{u,j}\land\neg z_{u,j-1}).
```

Required tool strengthening:

```math
x_{i,j}\rightarrow(z_{u,j-1}\lor t_{u,j}),\qquad u\in R_i.
```

Từ position 2, mỗi inserted tool phải được job tại position đó yêu cầu:

```math
t_{u,j}\rightarrow\bigvee_{i:u\in R_i}x_{i,j},
\qquad j=2,\ldots,N'.
```

Nếu không active job nào yêu cầu tool `u`, disjunction rỗng tạo unit clause
`not t[u,j]`. Position 1 được loại khỏi strengthening này vì exact magazine
capacity bắt buộc `c` initial insertions, trong đó có thể có filler tools.

### 7.5 Adjacency pruning

Tại bound `k`, nếu:

```math
c+d_{i,h}>k,
```

thì cấm `i` đứng ngay trước `h` bằng:

```math
\neg x_{i,j}\lor\neg x_{h,j+1}.
```

Trong standard mode, clauses được tạo lại theo từng bound. Trong incremental
mode, chỉ delta clauses mới được thêm; tập clauses tăng đơn điệu khi `k` giảm.

### 7.6 Global insertion cardinality

Standard mode dùng một sequential counter mới cho từng bound:

```python
CardEnc.atmost(
    lits=t_literals,
    bound=k,
    vpool=vpool,
    encoding=EncType.seqcounter,
)
```

Incremental mode tạo đúng một lần:

```python
ITotalizer(
    lits=t_literals,
    ubound=initial_ub - 1,
    top_id=vpool.top,
)
```

Sau khi copy clauses/RHS, `IDPool.top` được đồng bộ với `totalizer.top_id` và
đối tượng native totalizer được giải phóng. Bound `k` được áp đặt bằng
assumption:

```text
-totalizer.rhs[k]
```

nghĩa là tổng `t` không vượt `k`. Nếu `k >= len(t_literals)`, cardinality là
vacuous và không cần assumption.

## 8. Hai chế độ tối ưu

### Standard

Với mỗi `k = UB-1, UB-2, ..., LB`:

1. build toàn bộ CNF cho `k`;
2. tạo một CaDiCaL worker process;
3. solve;
4. đóng worker;
5. validate model nếu SAT;
6. dừng tại UNSAT đầu tiên.

### Incremental

Với mỗi problem:

1. build CNF bất biến và `ITotalizer` một lần;
2. tạo một persistent CaDiCaL worker;
3. với mỗi `k`, gửi adjacency delta và assumption `-rhs[k]`;
4. giữ lại toàn bộ clauses và learned state cho bound sau;
5. đóng worker khi tìm thấy UNSAT, đạt LB, timeout, lỗi hoặc bị ngắt.

Cả hai mode đều giảm `k` đúng một đơn vị, không binary search và không jump
theo validated KTNS cost.

## 9. Multiprocessing, timeout và ngắt chương trình

Time limit là tổng ngân sách cho một problem, bao gồm preprocessing, CNF build
và SAT search. Trước mỗi solve, worker chỉ nhận phần thời gian còn lại.

- Standard mode dùng một child process cho mỗi SAT call.
- Incremental mode dùng một persistent child process cho mỗi problem.
- Parent chờ kết quả qua pipe và theo dõi cả pipe lẫn process sentinel.
- Khi hết hạn, parent gọi `terminate()`, chờ ngắn, rồi `kill()` nếu cần.
- Không có silent fallback sang SAT solver khác.

Khi timeout:

- status là `TIMEOUT`;
- `best_cost` vẫn là một upper bound khả thi;
- `optimum` để trống vì chưa có chứng nhận tối ưu.

Khi người dùng nhấn `Ctrl+C`:

- worker hiện tại được dừng và thu dọn;
- instance đang chạy dở không được đưa vào kết quả;
- CSV được ghi nguyên tử với các instance đã hoàn tất;
- chương trình thoát với code `130`.

## 10. Decode và validation độc lập

Sau mỗi SAT result, validator không tin model một cách trực tiếp. Nó kiểm tra:

1. mỗi position có đúng một active job;
2. reduced sequence là permutation;
3. `z[u,0]` đều false;
4. mỗi magazine có đúng `c` tools;
5. requirements của job là tập con magazine;
6. mọi `t[u,j]` đúng với transition `0 -> 1` của `z`;
7. tổng `t` không vượt bound `k`;
8. reconstruction chứa đúng mọi original job;
9. KTNS trên reconstructed full sequence có cost không vượt `k`.

Optimality được chứng nhận bởi linear descending search: nếu có nghiệm khả thi
cost `b` và bound `b-1` là UNSAT thì `b` là optimum. Nếu đạt `LB` với SAT thì
`LB` là optimum. Timeout không tạo chứng nhận tối ưu.

## 11. Output và CSV

Console in cho từng problem:

- mode và problem ID;
- số original/reduced/dominated jobs;
- dominance mapping;
- LB, initial UB và greedy sequence;
- từng SAT iteration: `k`, status, số variables/clauses và solve time;
- optimum hoặc best feasible cost;
- reduced/full sequence;
- KTNS verification cost và total runtime.

Tên CSV mặc định:

```text
ssp_result_yyyy-mm-dd-hh-mm-ss.csv
```

Nếu bị `KeyboardInterrupt`:

```text
ssp_result_yyyy-mm-dd-hh-mm-ss_interupt.csv
```

Hậu tố `interupt` được giữ đúng theo giao diện đã yêu cầu. Nếu dùng
`--csv custom.csv`, file partial là `custom_interupt.csv`.

CSV được ghi qua temporary file rồi `os.replace`, tránh để lại file hoàn chỉnh
giả nếu việc ghi thất bại. Các cột hiện tại:

```text
problem, mode, status, n, n_reduced, dominated, lb, initial_ub,
best_cost, optimum, sat_calls, total_vars_last, total_clauses_last,
sat_time, total_time
```

## 12. API chính

```python
from src.parser import parse_file
from src.optimize import optimize_instance

instances = parse_file("data/Catanzaro/datA1")

standard = optimize_instance(instances[0], time_limit=600)
incremental = optimize_instance(
    instances[0],
    time_limit=600,
    incremental=True,
)
```

Các API thấp hơn:

- `preprocess_dominance(instance)`;
- `pairwise_distances(reduced_instance)`;
- `ktns(sequence, requirements, m, c)`;
- `build_cnf(reduced_instance, k, distances)`;
- `build_incremental_cnf(reduced_instance, max_k, distances)`;
- `solve_cnf(build, time_limit)`;
- `IncrementalSolverSession`;
- `validate_sat_solution(...)`.

## 13. Cấu trúc source

```text
src/
  cli.py          CLI và lifecycle của nhiều instances
  parser.py       input discovery và parser
  model.py        dataclasses/result records
  dominance.py    dominance và reconstruction
  distances.py    pairwise distance
  ktns.py         KTNS evaluator
  upper_bound.py  all-start greedy upper bound
  encoding.py     standard CNF, ITotalizer và adjacency clauses
  solver.py       CaDiCaL multiprocessing workers
  validate.py     decode và independent validation
  optimize.py     standard/incremental descending search
  report.py       console và atomic CSV output
```

`src/__main__.py` cung cấp `python -m src`; `src/__init__.py` export các API
cấp cao.

## 14. Kiểm thử và kết quả xác minh

Chạy test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Test suite bao phủ:

- parser cho Catanzaro, Crama, Yanasse và toàn bộ supplied data;
- việc bỏ qua `min/max` và best-known;
- dominance chains, duplicates và reconstruction;
- KTNS so với exhaustive magazine configurations;
- structural order encoding và sequential-counter position AMO;
- exact magazine counter và truth table của `t`;
- strengthening insert-tool từ position 2 và initial filler exception;
- adjacency pruning và tính đơn điệu của adjacency delta;
- `ITotalizer` so với standard cardinality trên nhiều bound;
- standard/incremental optimum so với exhaustive job permutations;
- timeout, worker reuse, process cleanup và `KeyboardInterrupt`;
- CLI, mode trong CSV, timestamped filenames và partial CSV.

Trạng thái xác minh tại thời điểm viết tài liệu:

- 33 unit/integration tests thành công;
- parser đọc 168 file / 1.671 instances;
- 80 random small instances bổ sung cho kết quả
  `standard == incremental == exhaustive`;
- `dummy.txt` trả optimum `11` ở incremental mode;
- `datA1/problem-2` dùng cùng một incremental worker cho các bound `12`, `11`,
  `10` và trả optimum `11`.

## 15. Các bảo đảm và giới hạn hiện tại

- Kết quả deterministic với cùng input, phiên bản dependency và solver.
- Chỉ `cadical300` được dùng; thiếu backend sẽ tạo configuration error rõ ràng.
- Không dùng best-known value, MaxSAT, binary search, randomization hay local
  search.
- Không chạy các instance song song; multiprocessing chỉ cô lập SAT solver để
  quản lý timeout và interruption.
- Time limit có thể bị vượt nhẹ bởi chi phí IPC/process termination, nhưng
  worker sẽ không tiếp tục chạy nền sau timeout hoặc `Ctrl+C`.
- Full benchmark có thể tốn nhiều thời gian; test suite chỉ exact-solve các
  instance nhỏ và smoke-parse toàn bộ dataset.
