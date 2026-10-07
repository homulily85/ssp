import math
import os
import time
import threading
from pysat.formula import IDPool
from pysat.card import CardEnc, EncType
from pysat.solvers import Glucose4
import openpyxl
from openpyxl import Workbook
job_p = 0
def export_to_excel(data_row, excel_filename="results_V2_2.xlsx"):
    headers = [
        "Instances",
        "n",
        "m",
        "c",
        "var",
        "clause",
        "t_encode",
        "t_solve",
        "status",
        "k_upper_bound",
        "k",
    ]

    if not os.path.exists(excel_filename):
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
    else:
        wb = openpyxl.load_workbook(excel_filename)
        ws = wb.active

    ws.append(
        [
            data_row["Instances"],
            data_row["n"],
            data_row["m"],
            data_row["c"],
            data_row["var"],
            data_row["clause"],
            round(data_row["t_encode"], 4),
            round(data_row["t_solve"], 4),
            data_row["status"],
            data_row["k_upper_bound"], 
            data_row["k"],
        ]
    )
    wb.save(excel_filename)
    print(f"📊 Đã ghi bổ sung kết quả vào {excel_filename}")


removed_jobs = {}
def read_input(file_name):
    removed_jobs.clear()
    with open(file_name, 'r') as f:
        lines = [line.strip() for line in f if line.strip()]
    
    dong_dau_tien = lines[0].strip().split()
    if len(dong_dau_tien) >= 3:
        l = 1
        n, m, C = map(int, dong_dau_tien[:3])
    else:
        l = 3
        n = int(lines[0].strip())
        m = int(lines[1].strip())
        C = int(lines[2].strip())

    matrix = []
    for i in range(l, l + m):
        row = list(map(int, lines[i].split()))
        matrix.append(row)
        
    T = {}
    for i in range(n):
        job_id = i + 1
        T[job_id] = [u + 1 for u in range(m) if matrix[u][i] == 1]
    
    valid_jobs = set(range(1, n+1))
    for a in range(1, n+1):
        for b in range(1, n+1):
            if a != b and set(T[a]).issubset(set(T[b])):
                removed_jobs[a] = b
                if a in valid_jobs:
                    valid_jobs.remove(a)
    
    T = {j: T[j] for j in valid_jobs}
    n = len(valid_jobs)

    return n, m, C, matrix, T
def compute_greedy_upper_bound(n, m, C, T):
    # 1. Đếm tần suất tool và sắp xếp công việc (O(n log n))
    tool_counts = {u: sum(1 for i in range(1, n+1) if u in T[i]) for u in range(1, m+1)}
    job_seq = sorted(range(1, n+1), key=lambda i: sum(tool_counts[u] for u in T[i]), reverse=True)
    global job_p
    job_p = job_seq[0]
    K_greedy, current_bin = 0, set()
    bin_states = {} 
    
    for idx, job in enumerate(job_seq):
        step = idx + 1 
        required = set(T[job])
        missing = required - current_bin          
        K_greedy += len(missing)
        current_bin.update(missing)
        
        # Lọc danh sách tool cũ dưới dạng list để tháo an toàn, tránh lỗi KeyError
        old_tools = list(current_bin - required)
        while len(current_bin) > C and old_tools:
            current_bin.remove(old_tools.pop())
            
        # Trường hợp đặc biệt dữ liệu lỗi
        while len(current_bin) > C:
            current_bin.pop()
            
        bin_states[step] = list(current_bin)
            
    print(f"\n--- 🛡️ KIỂM TRA ĐỘ CHÍNH XÁC CỦA THUẬT TOÁN THAM LAM ---")
    
    final_sequence = []
    for job in job_seq:
        final_sequence.append(job)
        for child, parent in removed_jobs.items():
            if parent == job:
                final_sequence.append(child)
    print(f"Chuỗi công việc tham lam đề xuất: {final_sequence}")
    n=len(final_sequence)
    # Gọi hàm check của bạn (trả về số lần lắp thực tế nếu đúng, False nếu sai)
    check_result = verify_solution(n, m, C, T, final_sequence, bin_states)
    
    if check_result is not False:
        print(f"🎉 Kết quả: Hàm tính tham lam HOÀN TOÀN CHÍNH XÁC (Khay chứa hợp lệ, số tool khớp K = {K_greedy})")
    else:
        print(f"💥 Kết quả: Hàm tính tham lam đang bị SAI LOGIC so với luật bài toán!")
        
    return K_greedy

def verify_solution(n, m, C, T, job_sequence, bin_states):
    errors = []
    if len(job_sequence) != n or set(job_sequence) != set(range(1, n + 1)):
        errors.append("❌ Lỗi: Thứ tự công việc không hợp lệ!")
        
    calculated_switches = 0
    prev_bin = set()
    
    for idx, job in enumerate(job_sequence):
        step = idx + 1
        current_bin = set(bin_states[step])
        
        if len(current_bin) > C:
            errors.append(f"❌ Lỗi bước {step}: Khay chứa vượt quá sức chứa C!")
        if not set(T[job]).issubset(current_bin):
            errors.append(f"❌ Lỗi bước {step}: Khay thiếu dụng cụ cho công việc {job}!")
            
        if step == 1:
            calculated_switches += len(current_bin)
        else:
            calculated_switches += len(current_bin - prev_bin)
        prev_bin = current_bin

    if errors:
        for err in errors: print(err)
        return False
    return calculated_switches


def run_pipeline():
    file_name = input("Nhập tên file dữ liệu: ")
    
    # ⏱️ BẮT ĐẦU TÍNH THỜI GIAN TOÀN BỘ LUỒNG (Bao gồm đọc file)
    global_start_time = time.perf_counter()
    TIME_LIMIT = 600.0 
    
    file_path = os.path.join("DATASSP", file_name) 
    
    try:
        n, m, C, matrix, T = read_input(file_path)
    except Exception as e:
        print(f"❌ Lỗi đọc file: {e}")
        return

    print(f"\n--- ĐỌC DỮ LIỆU ĐẦU VÀO ---")
    print(f"Công việc: {n} | Dụng cụ: {m} | Sức chứa khay: {C}")

    # 1. Xác định Cận trên ban đầu (Upper Bound của K)
    K_upper_bound = compute_greedy_upper_bound(n, m, C, T)
    
    current_K = K_upper_bound
    best_model = None
    best_K = None
    total_t_encode = 0.0
    total_t_solve = 0.0
    last_vars = 0
    last_clauses = 0
    status = "TIMEOUT"
    
    t_enc_start = time.perf_counter()
    vpool = IDPool()
    allclause = []
    print(job_p)
    for j in range(1, n+1):
        listbien = [vpool.id(("z", u, j)) for u in range(1, m+1)]
        allclause.extend(CardEnc.atmost(lits=listbien, bound=C, vpool=vpool, encoding=EncType.seqcounter).clauses)
    
    for i in range(1, n+1):
        if i == job_p: 
            listbien = [vpool.id(("x", i, j)) for j in range(1, math.ceil(n/2) + 1)]
        else:
            listbien = [vpool.id(("x", i, j)) for j in range(1, n+1)]
        allclause.extend(CardEnc.equals(lits=listbien, bound=1, vpool=vpool, encoding=EncType.seqcounter).clauses)

    for j in range(1, n+1):
        listbien = [vpool.id(("x", i, j)) for i in range(1, n+1)]
        allclause.extend(CardEnc.equals(lits=listbien, bound=1, vpool=vpool, encoding=EncType.seqcounter).clauses)

    for i in range(1, n+1):
        for u in T[i]:
            for j in range(1, n+1):
                allclause.append([-vpool.id(('x', i, j)), vpool.id(('z', u, j))])

    for u in range(1, m+1):
        for j in range(1, n+1):
            if j == 1: 
                allclause.append([-vpool.id(('t', u, j)), vpool.id(('z', u, j))])
                allclause.append([-vpool.id(('z', u, j)), vpool.id(('t', u, j))])
            else:
                allclause.append([-vpool.id(('t', u, j)), vpool.id(('z', u, j))])
                allclause.append([-vpool.id(('t', u, j)), -vpool.id(('z', u, j-1))])
                allclause.append([vpool.id(('t', u, j)), -vpool.id(('z', u, j)), vpool.id(('z', u, j-1))])

    t_vars = [vpool.id(("t", u, j)) for u in range(1, m+1) for j in range(1, n+1)]  
    last_vars = vpool.top
    t_enc_end = time.perf_counter()
    total_t_encode += t_enc_end - t_enc_start
    
    print(f"\n🚀 Bắt đầu vòng lặp while tìm K tối ưu (Cận trên khởi điểm: {current_K})...")
    
    while current_K >= 0 :
        elapsed_time = time.perf_counter() - global_start_time
        if elapsed_time > TIME_LIMIT:
            print(f"\n⚠️ HẾT GIỜ! Luồng bị ngắt vì vượt quá giới hạn {TIME_LIMIT} giây.")
            status = "SAT" if best_K is not None else "TIMEOUT"
            break
        listbien = []
        t_enc_start = time.perf_counter()
        for u in range(1, m+1):
            for j in range(1, n+1):
                listbien.append(vpool.id(("t", u, j)))
        k_clauses = (CardEnc.atmost(lits=listbien, bound=current_K, vpool=vpool, encoding=EncType.seqcounter).clauses)

        t_enc_end = time.perf_counter()
        total_t_encode += t_enc_end - t_enc_start 

        last_clauses = len(allclause) + len(k_clauses)
        
        # Giải SAT
        solver = Glucose4()
        for clause in allclause:
            solver.add_clause(clause)
        for clause in k_clauses:
            solver.add_clause(clause)
            
        remaining_time = TIME_LIMIT - (time.perf_counter() - global_start_time)
        
        # Nếu thời gian còn lại quá ít hoặc đã âm, ngắt luôn vòng lặp
        if remaining_time <= 0:
            print(f"\n⚠️ HẾT GIỜ! Luồng bị ngắt do chạm giới hạn {TIME_LIMIT} giây.")
            status = "SAT" if best_K is not None else "TIMEOUT"
            solver.delete()
            break
            
        timer = threading.Timer(remaining_time, solver.interrupt)
        timer.start()
        t_solve_start = time.perf_counter()
        is_sat = solver.solve_limited(expect_interrupt=True)
        t_solve_end = time.perf_counter()
        timer.cancel()
        total_t_solve += t_solve_end - t_solve_start

        if is_sat:
            # Lưu lại kết quả tốt nhất hiện tại
            best_model = set(solver.get_model())
            best_K = current_K
            best_vpool = vpool
            print(f"✔️ SAT với K = {current_K}")
            
            # Giảm K đi 1 đơn vị để tìm phương án tối ưu hơn ở vòng lặp sau
            current_K -= 1
        else:
            # Kiểm tra xem có phải do timeout
            elapsed_time = time.perf_counter() - global_start_time
            if elapsed_time >= TIME_LIMIT:
                print(f"⏱️ Timeout khi kiểm tra K = {current_K}, chưa kịp tìm nghiệm.")
                status = "SAT" if best_K is not None else "TIMEOUT"
                solver.delete()
                break
            else:
                print(f"❌ UNSAT với K = {current_K}. Điểm dừng tối ưu đã đạt được!")
                status = "OPTIMAL" if best_K is not None else "UNSAT"
                solver.delete()
                break
            
        solver.delete()

    # ⏱️ KẾT THÚC BẤM GIỜ TOÀN BỘ LUỒNG
    total_elapsed_time = time.perf_counter() - global_start_time

    # 3. XUẤT KẾT QUẢ CUỐI CÙNG SAU KHI KẾT THÚC VÒNG LẶP
    print("\n" + "="*20 + " KẾT QUẢ TỔNG HỢP LUỒNG " + "="*20)
    print(f"⏱️ Tổng thời gian thực thi : {total_elapsed_time:.4f} s")
    
    if best_model is not None:
        # Trích xuất dữ liệu để Validator kiểm tra
        job_sequence = []
        bin_states = {}
        for j in range(1, n+1):
            for i in range(1, n+1):
                if best_vpool.id(('x', i, j)) in best_model:
                    job_sequence.append(i)
            bin_states[j] = [u for u in range(1, m+1) if best_vpool.id(('z', u, j)) in best_model]

        final_sequence = []
        for job in job_sequence:
            final_sequence.append(job)
            for child, parent in removed_jobs.items():
                if parent == job:
                    final_sequence.append(child)

        n=len(final_sequence)

        check_result = verify_solution(n, m, C, T, final_sequence, bin_states)
        if(check_result):
            print(f"🎯 Giá trị K tối ưu nhất tìm được: {best_K}")
            print(f"Chuỗi công việc tốt nhất: {final_sequence}")
        else: print("Kết quả sai")

    else:
        print("❌ Không tìm thấy bất kỳ phương án SAT nào khả thi trong thời gian cho phép.")
    excel_data = {
        "Instances": file_name,
        "n": n,
        "m": m,
        "c": C,
        "var": last_vars,
        "clause": last_clauses,
        "t_encode": total_t_encode,
        "t_solve": total_t_solve,
        "status": status,
        "k_upper_bound":K_upper_bound,
        "k": best_K if best_K is not None else "-",
    }
    export_to_excel(excel_data, "results_V2_2.xlsx")
        
# Chạy chương trình
if __name__ == "__main__":
    run_pipeline()