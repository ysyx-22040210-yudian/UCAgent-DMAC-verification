module dmac_wrapper (
  input wire clk,
  input wire rst_n,
  input wire host_rd_req,
  input wire [31:0] host_rd_haddr,
  input wire [31:0] host_rd_len,
  input wire host_wr_req,
  input wire [31:0] host_wr_haddr,
  input wire [31:0] host_wr_len,
  input wire mem_rd_ready,
  input wire [63:0] mem_rd_data,
  input wire mem_wr_ready,
  input wire dev_rd_req,
  input wire dev_wr_req,
  input wire [15:0] dev_wr_data
);
wire host_rd_ack;
wire host_rd_done;
wire host_wr_ack;
wire host_wr_done;
wire mem_rd_valid;
wire [31:0] mem_rd_addr;
wire mem_wr_valid;
wire [31:0] mem_wr_addr;
wire [63:0] mem_wr_data;
wire dev_rd_ack;
wire [15:0] dev_rd_data;
wire dev_wr_ack;
dmac u_dut (.clk(clk), .rst_n(rst_n), .host_rd_req(host_rd_req), .host_rd_haddr(host_rd_haddr), .host_rd_len(host_rd_len), .host_wr_req(host_wr_req), .host_wr_haddr(host_wr_haddr), .host_wr_len(host_wr_len), .mem_rd_ready(mem_rd_ready), .mem_rd_data(mem_rd_data), .mem_wr_ready(mem_wr_ready), .dev_rd_req(dev_rd_req), .dev_wr_req(dev_wr_req), .dev_wr_data(dev_wr_data), .host_rd_ack(host_rd_ack), .host_rd_done(host_rd_done), .host_wr_ack(host_wr_ack), .host_wr_done(host_wr_done), .mem_rd_valid(mem_rd_valid), .mem_rd_addr(mem_rd_addr), .mem_wr_valid(mem_wr_valid), .mem_wr_addr(mem_wr_addr), .mem_wr_data(mem_wr_data), .dev_rd_ack(dev_rd_ack), .dev_rd_data(dev_rd_data), .dev_wr_ack(dev_wr_ack));
dmac_checker u_checker (.clk(clk), .rst_n(rst_n), .host_rd_req(host_rd_req), .host_rd_haddr(host_rd_haddr), .host_rd_len(host_rd_len), .host_wr_req(host_wr_req), .host_wr_haddr(host_wr_haddr), .host_wr_len(host_wr_len), .mem_rd_ready(mem_rd_ready), .mem_rd_data(mem_rd_data), .mem_wr_ready(mem_wr_ready), .dev_rd_req(dev_rd_req), .dev_wr_req(dev_wr_req), .dev_wr_data(dev_wr_data), .host_rd_ack(host_rd_ack), .host_rd_done(host_rd_done), .host_wr_ack(host_wr_ack), .host_wr_done(host_wr_done), .mem_rd_valid(mem_rd_valid), .mem_rd_addr(mem_rd_addr), .mem_wr_valid(mem_wr_valid), .mem_wr_addr(mem_wr_addr), .mem_wr_data(mem_wr_data), .dev_rd_ack(dev_rd_ack), .dev_rd_data(dev_rd_data), .dev_wr_ack(dev_wr_ack));
endmodule
