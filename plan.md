# 1. Mục tiêu

Xây dựng một chương trình Python giải chính xác bài toán Job Sequencing and Tool Switching Problem (SSP) bằng SAT với:

* PySAT;
* CaDiCaL 3.0;
* dominance preprocessing;
* greedy upper-bound construction;
* KTNS để đánh giá chính xác một job sequence cố định;
* SAT encoding sử dụng \(x,y,z,s,t\);
* cardinality constraint trên tổng \(t\) được mã hóa bằng sequential counter;
* linear descending search từ upper bound xuống optimum.

Chương trình phải xử lý nhiều problem trong cùng một file input.

Không sử dụng dòng

```text
best known value of the number of tool setups: ...
```

trong bất kỳ bước tính toán nào.

---

# 2. Cấu trúc dữ liệu

Với mỗi instance:

$$
J=\{0,\ldots,n-1\}
$$

là tập jobs và

$$
U=\{0,\ldots,m-1\}
$$

là tập tools.

Input matrix có kích thước

$$
m\times n.
$$

Quan trọng:

* mỗi **hàng** là một tool;
* mỗi **cột** là một job.

Định nghĩa

$$
R_i=\{u\in U:A_{u,i}=1\}.
$$

Lưu mỗi instance dưới dạng tương đương:

```python
SSPInstance:
    name
    n
    m
    c
    min_tools
    max_tools
    matrix
    requirements: list[set[int]]
```

Parser phải kiểm tra:

$$
|R_i|\le c
$$

và nếu metadata `min`, `max` tồn tại:

$$
min\le |R_i|\le max.
$$

---

# 3. Parser

Parser đọc metadata chung:

```text
n=10
m=10
min=2
max=4
c=4
```

sau đó nhận dạng các block:

```text
problem 1:
---------
...
```

Mỗi problem phải lấy đúng \(m\) dòng, mỗi dòng có đúng \(n\) giá trị Boolean.

Bỏ qua:

* dòng trống;
* dòng chứa dấu `-----`;
* dòng `best known value ...`.

Không sử dụng best-known value để khởi tạo UB, LB hay kiểm tra optimum.

---

# 4. Dominance preprocessing

## 4.1. Dominance rule

Nếu hai jobs \(i,h\) thỏa

$$
R_i\subseteq R_h,
$$

thì job \(i\) có thể được loại khỏi bài toán SAT thu gọn.

Lý do là magazine configuration đủ để thực hiện \(h\) cũng đủ để thực hiện \(i\). Sau khi giải bài toán thu gọn, \(i\) có thể được chèn sát \(h\) mà không làm tăng số lần nạp tool.

Trường hợp

$$
R_i=R_h
$$

cũng được xử lý như symmetry/dominance: chỉ giữ một representative.

## 4.2. Không được loại theo kiểu pairwise tuần tự đơn giản

Tránh tình trạng:

$$
R_i\subset R_h\subset R_q
$$

nhưng \(i\) ánh xạ vào \(h\), trong khi \(h\) cũng bị xóa.

Thay vào đó:

1. group các jobs có cùng \(R_i\);
2. tìm các tool sets inclusion-maximal;
3. giữ đúng một canonical job cho mỗi maximal set;
4. tất cả jobs còn lại phải được ánh xạ trực tiếp vào một active representative có requirement chứa nó.

Active set:

$$
J'=\{i:\ R_i \text{ là inclusion-maximal representative}\}.
$$

Với mỗi removed job \(i\), lưu

```python
dominator[i] = h
```

với

$$
h\in J',
\qquad
R_i\subseteq R_h.
$$

Nếu có nhiều dominator phù hợp, dùng quy tắc deterministic:

1. nhỏ nhất theo \(|R_h|\);
2. nếu hòa, nhỏ nhất theo original job index.

Lưu thêm

```python
dominated_by[h] = [i1, i2, ...]
```

theo thứ tự job ID tăng dần.

## 4.3. Reconstruction

Nếu SAT solver trả sequence thu gọn

$$
\pi'=(h_1,h_2,\ldots,h_q),
$$

khôi phục sequence đầy đủ bằng cách thay mỗi representative \(h\) bởi block

$$
[\text{dominated\_by}[h], h].
$$

Ví dụ:

```text
reduced:
[7, 3, 9]

dominated_by[7] = [1, 5]
dominated_by[3] = []
dominated_by[9] = [2]

full:
[1, 5, 7, 3, 2, 9]
```

Tất cả removed jobs phải xuất hiện đúng một lần trong reconstructed sequence.

## 4.4. Invariant cần kiểm thử

Preprocessing phải bảo toàn optimum:

$$
OPT_{\text{original}}=OPT_{\text{reduced}}.
$$

Cần có unit tests cho tính chất reconstruction không làm tăng tool-switch cost.

---

# 5. Lower bound cơ bản

Tính:

$$
U^*=\bigcup_{i\in J}R_i.
$$

Mọi required tool phải được nạp ít nhất một lần, đồng thời initial magazine phải nạp \(C\) tools.

Do đó:

$$
LB=\max(C,|U^*|).
$$

Có thể dùng LB để dừng search.

Không cần thêm lower bound phức tạp trong phiên bản đầu tiên.

---

# 6. Tiền xử lý pairwise distance

Trên các active jobs sau dominance preprocessing, tính trước:

$$
d_{i,h}
=
\max\{0,\ |R_i\cup R_h|-C\},
\qquad i\ne h.
$$

Lưu:

```python
d[i][h]
```

Đây là lower bound số insertions cần thiết nếu \(h\) đứng ngay sau \(i\).

---

# 7. Upper-bound algorithm

Sử dụng:

$$
\boxed{\text{All-start greedy sequencing + KTNS evaluation}}
$$

## 7.1. Greedy construction

Thực hiện trên reduced instance.

Với mỗi active job \(s\), chạy một greedy construction với \(s\) là starting job.

Tại mỗi bước, current job là \(i\). Chọn job chưa xếp \(h\) tối thiểu theo tuple lexicographic:

$$
\left(
d_{i,h},
-|R_i\cap R_h|,
h
\right).
$$

Tức:

1. ưu tiên \(d_{i,h}\) nhỏ nhất;
2. nếu hòa, ưu tiên overlap lớn nhất;
3. nếu vẫn hòa, chọn job ID nhỏ nhất.

Pseudo-code:

```text
for each start s:
    seq = [s]
    remaining = active_jobs - {s}

    while remaining is not empty:
        i = seq[-1]

        choose h minimizing:
            (
                d[i][h],
                -len(R[i] intersection R[h]),
                h
            )

        seq.append(h)
        remaining.remove(h)
```

## 7.2. Reconstruction trước khi đánh giá UB

Sau khi có reduced sequence:

```text
seq_reduced
```

phải reconstruct thành full sequence:

```text
seq_full
```

bằng dominance mapping.

Sau đó chạy KTNS trên **original instance**, không phải chỉ reduced instance.

Điều này đảm bảo UB được kiểm tra trực tiếp trên bài toán ban đầu.

---

# 8. KTNS evaluator

Cài đặt một routine độc lập:

```python
ktns(sequence, requirements, m, c)
```

trả về:

```python
cost
magazine_configs
```

Trong đó `cost` bao gồm cả \(C\) insertions ban đầu.

## 8.1. Initial magazine

Với first job \(i=\pi_1\):

$$
R_i\subseteq Z_1,
\qquad
|Z_1|=C.
$$

Khởi tạo:

```text
magazine = R[first_job]
```

Các slot còn lại:

$$
C-|R_{\pi_1}|
$$

được lấp bằng các tools có next-use gần nhất trong tương lai.

Nếu tool không bao giờ được sử dụng nữa, xem:

$$
nextUse=\infty.
$$

Initial cost:

$$
cost=C.
$$

## 8.2. Transition

Tại position \(j>1\), job hiện tại cần

$$
R_{\pi_j}.
$$

Tính:

$$
Missing=R_{\pi_j}\setminus Magazine.
$$

Nếu:

$$
|Missing|=q,
$$

phải loại đúng \(q\) tools khỏi:

$$
Magazine\setminus R_{\pi_j}.
$$

KTNS loại các tools có **next use xa nhất**.

Tool không bao giờ được dùng lại có next-use:

$$
\infty
$$

và phải được loại trước.

Sau đó:

$$
Magazine
=
(Magazine\setminus Evicted)
\cup Missing.
$$

Tăng:

$$
cost\leftarrow cost+|Missing|.
$$

Sau mỗi bước phải assert:

$$
R_{\pi_j}\subseteq Magazine
$$

và

$$
|Magazine|=C.
$$

## 8.3. Precompute next use

Không tìm next-use bằng scan từ đầu mỗi lần.

Xây backward table:

```python
next_use_after[position][tool]
```

hoặc danh sách sorted occurrence positions cho từng tool.

Mục tiêu là KTNS evaluation chạy gần:

$$
O(nm+nC\log C).
$$

---

# 9. Chọn upper bound

Với mỗi starting job:

1. greedy reduced sequence;
2. reconstruct full sequence;
3. KTNS evaluate;
4. giữ sequence có cost nhỏ nhất.

Kết quả:

```python
initial_ub
initial_sequence
```

Nếu nhiều sequence có cùng UB, chọn sequence lexicographically nhỏ hơn để kết quả deterministic.

---

# 10. SAT variables

SAT encoding chỉ áp dụng trên reduced instance.

Gọi:

$$
N'=|J'|.
$$

Remap active jobs thành local indices:

$$
0,\ldots,N'-1.
$$

Phải giữ:

```python
local_to_original
original_to_local
```

Sử dụng duy nhất một `IDPool`.

Các variables:

### Job order

$$
y_{i,j},
\qquad
j=1,\ldots,N'+1.
$$

### Exact job position

$$
x_{i,j},
\qquad
j=1,\ldots,N'.
$$

### Magazine

$$
z_{u,j},
\qquad
u=0,\ldots,m-1,
\quad
j=0,\ldots,N'.
$$

### Insertions

$$
t_{u,j},
\qquad
j=1,\ldots,N'.
$$

### Magazine order-counter

$$
s_{q,r,j}.
$$

Ở đây cần tránh nhầm \(q\) với tool ID.

\(q\) có nghĩa:

> đã xét \(q\) tools đầu tiên.

Do đó:

$$
q=0,\ldots,m,
$$

và

$$
r=0,\ldots,C+1.
$$

---

# 11. Job permutation encoding

Cho mỗi active job \(i\):

$$
y_{i,1}=\text{True},
$$

$$
y_{i,N'+1}=\text{False}.
$$

Monotonicity:

$$
y_{i,j+1}\rightarrow y_{i,j}.
$$

Implementation clause:

```text
¬y[i,j+1] ∨ y[i,j]
```

Liên kết:

$$
x_{i,j}
\leftrightarrow
(y_{i,j}\land\neg y_{i,j+1}).
$$

CNF implementation:

```text
¬x[i,j] ∨ y[i,j]

¬x[i,j] ∨ ¬y[i,j+1]

¬y[i,j] ∨ y[i,j+1] ∨ x[i,j]
```

Không tạo cardinality:

$$
\sum_jx_{i,j}=1.
$$

Điều này đã được structural encoding \(y\) đảm bảo.

---

# 12. At-most-one job per position

Với mỗi position \(j\):

$$
AMO(x_{1,j},\ldots,x_{N',j}).
$$

Phiên bản đầu tiên dùng pairwise encoding:

$$
\neg x_{i,j}\lor\neg x_{h,j},
\qquad i<h.
$$

Lý do:

* đơn giản;
* không cần auxiliary variables;
* với benchmark nhỏ \(n=10\), chi phí thấp;
* tránh đưa thêm cardinality encoder không cần thiết.

Không thêm ALO constraint cho position.

---

# 13. Job-tool requirements

Với mọi:

$$
u\in R_i
$$

và position \(j\):

$$
x_{i,j}\rightarrow z_{u,j}.
$$

Clause:

```text
¬x[i,j] ∨ z[u,j]
```

---

# 14. Magazine capacity order-counter

Ý nghĩa:

$$
s_{q,r,j}=1
$$

iff trong \(q\) tools đầu tiên có ít nhất \(r\) tools nằm trong magazine tại position \(j\).

Boundary:

$$
s_{q,0,j}=\text{True}
$$

cho mọi \(q\).

$$
s_{0,r,j}=\text{False}
$$

cho:

$$
r\ge1.
$$

Có thể thêm strengthening:

$$
s_{q,r,j}=\text{False}
\qquad
r>q.
$$

Recurrence:

$$
s_{q,r,j}
\leftrightarrow
\left[
s_{q-1,r,j}
\lor
\left(
z_{q-1,j}
\land
s_{q-1,r-1,j}
\right)
\right].
$$

Chú ý Python tool index là `q-1`.

Để encode:

$$
A\leftrightarrow B\lor(C\land D),
$$

dùng bốn clauses:

```text
¬A ∨ B ∨ C

¬A ∨ B ∨ D

¬B ∨ A

¬C ∨ ¬D ∨ A
```

Trong đó:

```text
A = s[q,r,j]
B = s[q-1,r,j]
C = z[q-1,j]
D = s[q-1,r-1,j]
```

Chỉ cần generate recurrence cho:

$$
1\le r\le\min(q,C+1).
$$

Exact capacity:

$$
s_{m,C,j}=\text{True},
$$

$$
s_{m,C+1,j}=\text{False}.
$$

Hai unit clauses:

```text
s[m,C,j]

¬s[m,C+1,j]
```

---

# 15. Empty initial magazine

Cho mọi tool \(u\):

$$
z_{u,0}=\text{False}.
$$

Unit clause:

```text
¬z[u,0]
```

---

# 16. Tool insertion variables

Định nghĩa:

$$
t_{u,j}
\leftrightarrow
(z_{u,j}\land\neg z_{u,j-1}).
$$

CNF:

```text
¬t[u,j] ∨ z[u,j]

¬t[u,j] ∨ ¬z[u,j-1]

¬z[u,j] ∨ z[u,j-1] ∨ t[u,j]
```

Với \(j=1\), vì:

$$
z_{u,0}=False,
$$

ta tự động có:

$$
t_{u,1}\leftrightarrow z_{u,1}.
$$

Do capacity bằng \(C\), tổng \(t_{u,1}\) tự động bằng \(C\).

---

# 17. Redundant strengthening constraint

Thêm đúng constraint đã thống nhất:

$$
x_{i,j}
\rightarrow
(z_{u,j-1}\lor t_{u,j}),
\qquad
u\in R_i.
$$

Áp dụng cho:

$$
j=1,\ldots,N'.
$$

Clause:

```text
¬x[i,j] ∨ z[u,j-1] ∨ t[u,j]
```

Với \(j=1\), do \(z_{u,0}=False\), clause trở thành:

$$
x_{i,1}\rightarrow t_{u,1}.
$$

Không thêm các strengthening constraints khác trong baseline implementation.

---

# 18. Adjacency pruning bằng \(d_{i,h}\)

Cho mỗi ordered pair active jobs:

$$
i\ne h,
$$

đã có:

$$
d_{i,h}
=
\max\{0,|R_i\cup R_h|-C\}.
$$

Với SAT bound hiện tại \(k\), nếu:

$$
C+d_{i,h}>k,
$$

thì \(i\) không thể nằm ngay trước \(h\).

Với mọi:

$$
j=1,\ldots,N'-1,
$$

thêm:

$$
\neg x_{i,j}
\lor
\neg x_{h,j+1}.
$$

Không tạo conditional cardinality cho \(d_{i,h}\) trong phiên bản này.

Chỉ dùng \(d_{i,h}\) để cấm adjacency trong trường hợp trên.

---

# 19. Global tool-switch cardinality

Giữ nguyên constraint ở mức mô hình:

$$
\sum_{j=1}^{N'}
\sum_{u\in U}
t_{u,j}
\le k.
$$

Đây là **cardinality constraint**.

Không tự xây custom counter cho constraint này.

Sử dụng PySAT:

```python
CardEnc.atmost(
    lits=t_literals,
    bound=k,
    vpool=vpool,
    encoding=EncType.seqcounter
)
```

sau đó:

```python
cnf.extend(card.clauses)
```

Thứ tự `t_literals` phải deterministic, ví dụ:

```text
t[0,1], t[1,1], ..., t[m-1,1],
t[0,2], ...
```

---

# 20. Special cases cho cardinality

Nếu:

$$
k<C,
$$

trả UNSAT ngay, không cần build CNF.

Nếu:

$$
k\ge mN',
$$

constraint global là vacuous.

Tuy nhiên trong actual optimization search, thường không xảy ra trường hợp này.

---

# 21. CNF builder API

Tạo routine:

```python
build_cnf(reduced_instance, k, d_matrix)
```

trả:

```python
CNFBuildResult:
    cnf
    vpool
    vars_x
    vars_y
    vars_z
    vars_t
    vars_s
```

Thứ tự generate constraints:

1. \(y\) boundary;
2. \(y\) monotonicity;
3. \(x\leftrightarrow y\);
4. AMO per position;
5. job-tool requirements;
6. magazine counter;
7. initial \(z_{u,0}\);
8. \(t\)-transition;
9. redundant \(x\rightarrow(z_{prev}\lor t)\);
10. adjacency pruning;
11. global sequential counter.

Kết quả nên log:

```text
number of primary variables
number of auxiliary variables
total variables
total clauses
```

---

# 22. CaDiCaL solver wrapper

Tạo wrapper:

```python
solve_cnf(build_result)
```

Mục tiêu dùng:

```python
Solver(
    name="cadical300",
    bootstrap_with=cnf.clauses,
    use_timer=True
)
```

Nếu environment không expose CaDiCaL 3.0, phải báo dependency/configuration error rõ ràng.

Không âm thầm fallback sang solver khác, vì benchmark cần nhất quán.

Thu thập:

```python
status
solve_time
model
solver_stats
```

nếu API hỗ trợ stats tương ứng.

---

# 23. Decode SAT model

Nếu SAT, decode sequence từ \(x\).

Tạo:

```python
decode_reduced_sequence(model, vars_x)
```

Với mỗi position \(j\), phải tìm đúng một job \(i\) sao cho:

$$
x_{i,j}=True.
$$

Assert:

```text
exactly one active job per position
every active job appears exactly once
```

Sau đó map local ID về original representative ID.

Tiếp theo reconstruct dominated jobs để thu full sequence.

---

# 24. Validate SAT solution

Không tin model một cách mù quáng.

Sau mỗi SAT result, chạy validator độc lập.

Kiểm tra reduced model:

$$
|Z_j|=C.
$$

Với job \(i\) ở \(j\):

$$
R_i\subseteq Z_j.
$$

Kiểm tra:

$$
t_{u,j}
=
1
\iff
z_{u,j}=1\land z_{u,j-1}=0.
$$

Tính:

$$
SATCost=
\sum_{j,u}t_{u,j}.
$$

Assert:

$$
SATCost\le k.
$$

Sau đó chạy KTNS trên reconstructed full sequence.

Lấy:

```python
full_cost = ktns(full_sequence)
```

Assert:

$$
full\_cost\le k.
$$

Nếu assertion này fail, có bug ở dominance preprocessing, reconstruction hoặc encoding.

---

# 25. Linear descending search

Sau UB construction:

```text
best_cost = initial_ub
best_sequence = initial_sequence
```

Nếu:

$$
best\_cost=LB,
$$

có thể kết luận optimal ngay.

Nếu không, search:

```text
for k = initial_ub - 1 down to LB:
    build CNF(k)
    solve with CaDiCaL

    if SAT:
        decode
        reconstruct
        validate

        best_cost = cost of validated full sequence
        best_sequence = full sequence

    else:
        optimum = best_cost
        stop
```

Để bám đúng yêu cầu **tìm kiếm tuần tự từ UB xuống**, mặc định giảm:

$$
k\leftarrow k-1
$$

sau mỗi SAT result.

Không binary search.

Không MaxSAT.

Không optimization API.

Nếu solver SAT tại:

$$
k=LB,
$$

thì:

$$
OPT=LB.
$$

---

# 26. Một optimization an toàn nhưng chưa bật mặc định

Có thể sau này cho phép:

```text
if validated_cost < k:
    jump directly to validated_cost - 1
```

vì đây vẫn là safe optimization.

Tuy nhiên phiên bản baseline phải dùng strict sequential descending search để kết quả thực nghiệm dễ giải thích.

---

# 27. Output cho mỗi problem

In hoặc lưu:

```text
Problem ID

Original jobs
Reduced jobs
Dominated jobs

Dominance mapping

Lower bound
Greedy/KTNS upper bound
Initial greedy sequence

For each SAT iteration:
    k
    SAT / UNSAT
    variables
    clauses
    solve time

Optimal cost
Optimal reduced sequence
Optimal reconstructed sequence

KTNS verification cost
Total runtime
```

Nên hỗ trợ xuất CSV tổng hợp:

```text
problem,
n,
n_reduced,
dominated,
lb,
initial_ub,
optimum,
sat_calls,
total_vars_last,
total_clauses_last,
sat_time,
total_time
```

---

# 28. Project structure đề xuất

```text
ssp_sat/
    parser.py
    model.py
    dominance.py
    distances.py
    ktns.py
    upper_bound.py
    encoding.py
    solver.py
    reconstruct.py
    validate.py
    main.py

tests/
    test_parser.py
    test_dominance.py
    test_ktns.py
    test_order_encoding.py
    test_magazine_counter.py
    test_transition.py
    test_adjacency.py
    test_small_exact.py
```

---

# 29. Unit tests bắt buộc

## Parser test

Với sample \(n=m=10\):

* phải đọc đủ 10 problems;
* mỗi matrix là \(10\times10\);
* mỗi \(R_i\) lấy theo **column**, không phải row;
* bỏ qua best-known lines.

## Dominance tests

Ví dụ:

$$
R_1=\{1,2\},
$$

$$
R_2=\{1,2,3\},
$$

$$
R_3=\{1,2,3,4\}.
$$

Chỉ \(R_3\) phải là maximal representative.

Reconstruction phải chứa cả ba jobs.

## Duplicate tests

Nếu:

$$
R_1=R_2,
$$

chỉ giữ một representative.

## Order encoding tests

Với một job, mọi satisfying assignment phải có đúng một transition:

$$
1\rightarrow0
$$

trong \(y\), và đúng một \(x\) True.

## Position AMO test

Không vị trí nào chứa hai jobs.

Kết hợp với job order encoding phải tạo một permutation.

## Magazine-counter test

Với small instance, enumerate các assignments cho \(z\) và kiểm tra CNF satisfiable iff:

$$
\sum_uz_{u,j}=C.
$$

## Transition test

Truth-table cho:

$$
t\leftrightarrow(z_j\land\neg z_{j-1}).
$$

Bốn trường hợp:

```text
0 -> 0 : t=0
0 -> 1 : t=1
1 -> 0 : t=0
1 -> 1 : t=0
```

## Adjacency test

Nếu:

$$
C+d_{i,h}>k,
$$

mọi model chứa:

$$
i@j,\ h@(j+1)
$$

phải UNSAT.

## KTNS test

Với sequence nhỏ, so sánh KTNS với brute-force enumeration của magazine configurations.

## End-to-end exact test

Sinh random instances nhỏ:

$$
n\le 7.
$$

Tính optimum bằng exhaustive enumeration:

1. enumerate toàn bộ job permutations;
2. đánh giá mỗi permutation bằng KTNS;
3. lấy minimum.

So sánh với SAT optimum.

Phải có:

$$
OPT_{SAT}=OPT_{bruteforce}.
$$

Đây là test quan trọng nhất.

---

# 30. Edge cases bắt buộc

Phải test riêng:

$$
C=M.
$$

Một job có:

$$
|R_i|=C.
$$

Tất cả jobs có cùng \(R_i\).

Chỉ còn một representative sau dominance.

Không có dominance nào.

Nhiều dominance chains.

$$
k<C.
$$

$$
LB=UB.
$$

Toàn bộ required tools vừa đủ magazine:

$$
\left|\bigcup_iR_i\right|\le C.
$$

Trong trường hợp cuối:

$$
OPT=C.
$$

---

# 31. Debug assertions

Trong development mode, bật assertions mạnh.

Sau preprocessing:

```text
every original job is either active
or maps to exactly one active dominator
```

và:

$$
R_i\subseteq R_{dominator(i)}.
$$

Sau reconstruction:

```text
len(sequence) == original_n
```

và:

```text
set(sequence) == set(original_jobs)
```

Sau KTNS:

$$
|Magazine_j|=C.
$$

$$
R_{\pi_j}\subseteq Magazine_j.
$$

Sau SAT decode:

```text
reduced sequence is a permutation of active jobs
```

Sau full reconstruction:

```text
KTNS(full_sequence) <= k
```

---

# 32. Không làm trong phiên bản đầu tiên

Không thêm:

* randomization;
* local search;
* simulated annealing;
* genetic algorithm;
* tabu search;
* MaxSAT;
* binary search trên \(k\);
* conditional cardinality dựa trên \(d_{i,h}\);
* KTNS dominance clauses trong SAT;
* symmetry-breaking ngoài dominance preprocessing;
* incremental SAT optimization;
* solver-specific phase tuning.

Mục tiêu phiên bản đầu tiên là có một implementation **đúng, deterministic, dễ kiểm chứng và phản ánh chính xác formulation**.

---

# 33. Pipeline cuối cùng

Pipeline toàn bộ chương trình:

```text
read input
    ↓
construct original R_i
    ↓
dominance preprocessing
    ↓
build active reduced instance
    ↓
compute d[i,h]
    ↓
all-start greedy sequencing
    ↓
reconstruct original sequence
    ↓
KTNS
    ↓
obtain UB
    ↓
compute LB
    ↓
for k = UB-1, UB-2, ..., LB:
        build SAT encoding
        add adjacency pruning for this k
        encode sum(t) <= k using sequential counter
        solve with CaDiCaL 3.0
        if SAT:
            decode
            reconstruct
            validate with KTNS
        else:
            stop
    ↓
return certified optimum + sequence
```

---

# 34. Acceptance criteria

Implementation được xem là hoàn thành khi:

1. parser đọc đúng toàn bộ supplied format;
2. không sử dụng best-known values;
3. dominance preprocessing có reconstruction chính xác;
4. greedy+KTNS sinh được một valid UB;
5. SAT encoding dùng đúng \(x,y,z,s,t\);
6. không có exactly-one cardinality trên \(x\);
7. magazine capacity dùng custom order counter \(s\);
8. \(\sum t\le k\) dùng PySAT sequential counter;
9. adjacency pruning dùng đúng

$$
C+d_{i,h}>k;
$$

10. solver là CaDiCaL 3.0;
11. linear descending search được sử dụng;
12. reconstructed sequence luôn khả thi;
13. objective SAT khớp KTNS validation;
14. trên các small instances,

$$
OPT_{SAT}=OPT_{bruteforce};
$$

15. chương trình báo optimum và optimal sequence cho từng problem.
