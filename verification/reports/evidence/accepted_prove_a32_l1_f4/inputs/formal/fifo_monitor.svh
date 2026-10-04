// Independent shift-queue oracle. No payload, ready or valid assumptions.
reg f_fifo_past = 0;
reg [COUNT_W-1:0] f_fifo_count;
reg [WIDTH-1:0] f_fifo_model [0:DEPTH-1];
assign f_count_out = f_fifo_count;
assign f_head_out = (f_fifo_count != 0) ? f_fifo_model[0] : 0;
always @(posedge clk) f_fifo_past <= 1;
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) f_fifo_count <= 0;
    else begin
        if (out_valid && out_ready)
            for (integer j = 0; j < DEPTH-1; j = j+1)
                f_fifo_model[j] <= f_fifo_model[j+1];
        if (in_valid && in_ready)
            f_fifo_model[f_fifo_count - (out_valid && out_ready)] <= in_data;
        case ({in_valid && in_ready, out_valid && out_ready})
            2'b10: f_fifo_count <= f_fifo_count + 1;
            2'b01: f_fifo_count <= f_fifo_count - 1;
            default: ;
        endcase
    end
end
always @(posedge clk) if (f_fifo_past && rst_n) begin
    A_CK_FIFO_COUNT: assert (count_q == f_fifo_count);
    A_CK_FIFO_RANGE: assert (count_q <= DEPTH && rd_ptr_q < DEPTH && wr_ptr_q < DEPTH);
    A_CK_FIFO_POINTER: assert (wr_ptr_q == ((int'(rd_ptr_q)+int'(count_q)) % DEPTH));
    A_CK_FIFO_VALID: assert (out_valid == (f_fifo_count != 0));
    A_CK_FIFO_READY: assert (in_ready == ((f_fifo_count < DEPTH) || (out_valid && out_ready)));
    A_CK_FIFO_HEAD: assert (!out_valid || out_data == f_fifo_model[0]);
    C_CK_FIFO_FULL_REPLACE: cover (f_fifo_count == DEPTH && push && pop);
    C_CK_FIFO_FULL: cover (f_fifo_count == DEPTH && !pop);
    C_CK_FIFO_EMPTY: cover (f_fifo_count == 0 && push);
end
generate for (genvar j=0; j<DEPTH; j=j+1) begin: f_slot
    always @(posedge clk) if (f_fifo_past && rst_n && j < f_fifo_count)
        assert (storage[(int'(rd_ptr_q)+j) % DEPTH] == f_fifo_model[j]); // CK-FIFO-ORDER per slot
end endgenerate
